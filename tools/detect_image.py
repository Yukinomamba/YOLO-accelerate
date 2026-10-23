#!/usr/bin/env python3
"""YOLOX-Tiny image inference: every Conv2d runs on the Verilated adam128 RTL.

CPU: dynamic symmetric quantization, dequantization, bias, BN, SiLU, graph ops,
decode, NMS and drawing. This is a functional co-simulation, not an SoC emulator.
"""
import argparse
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from adam_image_backend import AdamSimulator, ROOT, sha256


def official_module(source, relative, name):
    spec = importlib.util.spec_from_file_location(name, source / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path('build/upstream/YOLOX'))
    p.add_argument('--weights', type=Path, default=Path('build/models/yolox_tiny.pth'))
    p.add_argument('--simulator', type=Path, default=Path('build/image-cosim/obj/Vadam_conv128'))
    p.add_argument('--image', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True, help='annotated PNG/JPG; JSON saved alongside it')
    p.add_argument('--size', type=int, choices=[320, 416], default=416)
    p.add_argument('--confidence', type=float, default=0.25)
    p.add_argument('--nms', type=float, default=0.45)
    p.add_argument('--no-verify-integers', action='store_true',
                   help='skip scalar cross-check only; all convolutions still run on RTL')
    args = p.parse_args()
    if not 0 < args.confidence < 1 or not 0 < args.nms < 1:
        p.error('confidence and NMS thresholds must be between zero and one')
    if args.output.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        p.error('output must be PNG or JPG')
    if args.output.resolve() == args.image.resolve():
        p.error('output must differ from input image')
    return args


def main():
    args = parse_args()
    source = args.source.resolve()
    lock = json.loads((ROOT / 'config/yolox-tiny.lock.json').read_text())
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != lock['commit']:
        raise ValueError('upstream differs from pinned YOLOX commit')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        raise ValueError('upstream checkout must be clean')
    for name, expected in lock['source_sha256'].items():
        if sha256(source / name) != expected:
            raise ValueError(f'upstream source hash mismatch: {name}')
    if sha256(args.weights) != lock['weights_sha256']:
        raise ValueError('weights differ from pinned official YOLOX-Tiny checkpoint')
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    sys.path.insert(0, str(source))
    import cv2
    import numpy as np
    import torch
    from yolox.exp import get_exp
    from yolox.utils import postprocess
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    cv2.setNumThreads(1)
    preproc = official_module(source, 'yolox/data/data_augment.py', 'official_preproc').preproc
    classes = official_module(source, 'yolox/data/datasets/coco_classes.py', 'official_classes').COCO_CLASSES
    image = cv2.imread(str(args.image))
    if image is None:
        raise ValueError(f'cannot decode input image: {args.image}')
    model = get_exp(None, 'yolox-tiny').get_model().cpu().eval()
    checkpoint = torch.load(args.weights, map_location='cpu', weights_only=True)
    model.load_state_dict(checkpoint['model'], strict=True)
    del checkpoint
    gc.collect()
    convs = [(name, layer) for name, layer in model.named_modules() if isinstance(layer, torch.nn.Conv2d)]
    if len(convs) != 83:
        raise ValueError(f'pinned Tiny graph must have 83 convolutions, got {len(convs)}')
    for name, layer in convs:
        if (layer.groups != 1 or layer.dilation != (1, 1) or layer.padding_mode != 'zeros' or
                layer.kernel_size not in ((1, 1), (3, 3)) or layer.stride not in ((1, 1), (2, 2)) or
                layer.padding != (layer.kernel_size[0]//2,)*2):
            raise ValueError(f'unsupported layer {name}; there is no CPU convolution fallback')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tensor, ratio = preproc(image, (args.size, args.size))
    layers = []
    started = time.monotonic()
    with AdamSimulator(args.simulator, verify=not args.no_verify_integers,
                       stderr_path=args.output.with_suffix('.server.log')) as simulator:
        def replace(name, layer):
            weight = layer.weight.detach().numpy()
            scale_w = np.maximum(np.max(np.abs(weight), axis=(1, 2, 3)) / np.float32(127), np.float32(1e-12))
            quant_w = np.clip(np.rint(weight / scale_w[:, None, None, None]), -127, 127).astype(np.int8)
            bias = layer.bias.detach().numpy().copy() if layer.bias is not None else None

            def forward(value):
                if value.device.type != 'cpu' or value.ndim != 4 or value.shape[0] != 1:
                    raise ValueError('image co-simulation requires one CPU image')
                start = time.monotonic()
                activation = value.detach().numpy()[0]
                if not np.isfinite(activation).all():
                    raise ValueError(f'non-finite input in {name}')
                scale_a = np.float32(max(float(np.max(np.abs(activation))) / 127, 1e-12))
                quant_a = np.clip(np.rint(activation / scale_a), -127, 127).astype(np.int8)
                integers, stats = simulator.conv(quant_a, quant_w, layer.stride[0], layer.padding[0])
                # Only returned RTL INT32 values feed subsequent graph operators.
                output = integers.astype(np.float32) * (scale_a*scale_w[:, None, None])
                if bias is not None:
                    output += bias[:, None, None]
                stats.update(name=name, input_chw=list(activation.shape), output_chw=list(output.shape),
                             kernel=layer.kernel_size[0], stride=layer.stride[0], padding=layer.padding[0],
                             activation_scale=float(scale_a), weight_scales=scale_w.tolist(),
                             input_int8_sha256=hashlib.sha256(quant_a.tobytes()).hexdigest(),
                             weight_int8_sha256=hashlib.sha256(quant_w.tobytes()).hexdigest(),
                             useful_macs=int(output.size*layer.in_channels*layer.kernel_size[0]**2),
                             elapsed_seconds=time.monotonic()-start)
                layers.append(stats)
                print(f'[{len(layers):02d}/83] {name}: {stats["tile_commands"]} tiles, '
                      f'{stats["scalar_checked_values"]} checked, {stats["elapsed_seconds"]:.2f}s', flush=True)
                return torch.from_numpy(output[None])
            layer.forward = forward

        for name, layer in convs:
            replace(name, layer)
        with torch.inference_mode():
            prediction = model(torch.from_numpy(tensor).unsqueeze(0))
            output = postprocess(prediction, 80, conf_thre=args.confidence, nms_thre=args.nms,
                                 class_agnostic=True)[0]
        if len(layers) != 83 or sorted(x['name'] for x in layers) != sorted(x[0] for x in convs):
            raise RuntimeError('not all 83 convolution modules executed exactly once on RTL')
        simulator_manifest = simulator.manifest
    detections = []
    annotated = image.copy()
    if output is not None:
        for row in output.tolist():
            cid, score = int(row[6]), row[4]*row[5]
            box = [float(x/ratio) for x in row[:4]]
            detections.append({'class_id': cid, 'class_name': classes[cid], 'score': score,
                               'xyxy_original': box})
            x1, x2 = [int(np.clip(round(x), 0, image.shape[1]-1)) for x in (box[0], box[2])]
            y1, y2 = [int(np.clip(round(y), 0, image.shape[0]-1)) for y in (box[1], box[3])]
            color = (64+cid*53 % 192, 64+cid*97 % 192, 64+cid*139 % 192)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label = f'{classes[cid]} {score:.2f}'
            (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            tx, ty = min(x1, max(0, image.shape[1]-tw-4)), max(th+6, y1)
            cv2.rectangle(annotated, (tx, ty-th-6), (tx+tw+4, ty+baseline), color, -1)
            cv2.putText(annotated, label, (tx+2, ty-3), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    if not cv2.imwrite(str(args.output), annotated):
        raise RuntimeError('failed to write annotated image')
    counters = ('rtl_clock_cycles', 'rtl_mac_steps', 'rtl_active_cycles', 'tile_commands',
                'output_values', 'scalar_checked_values', 'useful_macs')
    result = {
        'mode': 'Verilator adam128 INT8 convolution + CPU FP32 remaining graph operators',
        'model': 'YOLOX-Tiny', 'input_size': args.size, 'original_hw': list(image.shape[:2]),
        'upstream_commit': lock['commit'], 'weights_sha256': sha256(args.weights),
        'image_sha256': sha256(args.image), 'annotated_image_sha256': sha256(args.output),
        'torch': torch.__version__, 'numpy': np.__version__, 'opencv': cv2.__version__,
        'preprocess': 'official non-legacy BGR, top-left resize, pad=114, CHW, no /255',
        'quantization': 'dynamic per-tensor activation + per-output-channel weight symmetric INT8 [-127,127]; '
                        'round ties to even; INT32 RTL accumulator; CPU FP32 dequant/bias; no calibration',
        'cpu_ops': ['preprocess', 'quantize/dequantize', 'bias', 'BatchNorm', 'SiLU', 'Focus',
                    'residual add', 'concat', 'MaxPool', 'nearest upsample', 'sigmoid', 'decode', 'NMS', 'draw'],
        'rtl_conv_layers': len(layers), 'cpu_conv_layers': 0,
        'integer_verification': not args.no_verify_integers,
        'confidence': args.confidence, 'nms_iou': args.nms, 'class_agnostic_nms': True,
        'detections': detections, 'totals': {key: sum(layer[key] for layer in layers) for key in counters},
        'elapsed_seconds': time.monotonic()-started, 'layers': layers,
        'simulator': {key: simulator_manifest[key] for key in ('verilator', 'binary_sha256', 'source_sha256')},
        'driver_source_sha256': {name: sha256(ROOT/name) for name in
                                 ('tools/detect_image.py', 'tools/adam_image_backend.py')},
        'scope': {'full_yolox_graph': True, 'all_convolutions_rtl': True, 'all_ops_rtl': False,
                  'static_int8_deployment': False, 'riscv_uart_ddr_simulated': False, 'board_run': False},
    }
    report = args.output.with_suffix('.json')
    report.write_text(json.dumps(result, indent=2) + '\n')
    print(f'PASS YOLOX-Tiny: 83 RTL convolutions, {len(detections)} detections -> {args.output}; report={report}')


if __name__ == '__main__':
    main()

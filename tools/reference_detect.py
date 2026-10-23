#!/usr/bin/env python3
"""Run official YOLOX preprocessing/model/NMS on a PC and save a golden JSON."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from audit_yolox import PIN


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--weights', type=Path, required=True)
    p.add_argument('--image', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--size', type=int, choices=[320, 416], default=416)
    p.add_argument('--model', choices=['yolox-nano', 'yolox-tiny'], default='yolox-nano')
    args = p.parse_args()
    source = args.source.resolve()
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != PIN:
        p.error('upstream commit differs from pinned audit')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        p.error('upstream checkout must be clean')
    sys.path.insert(0, str(source))
    import cv2
    import torch
    from yolox.exp import get_exp
    from yolox.utils import postprocess
    # 直接加载官方预处理；避免引入仅训练数据集需要的 COCO 依赖。
    spec = importlib.util.spec_from_file_location('official_preproc', source/'yolox/data/data_augment.py')
    preproc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preproc)
    image = cv2.imread(str(args.image))
    if image is None:
        p.error('cannot decode image')
    torch.set_num_threads(2)
    model = get_exp(None, args.model).get_model().eval()
    checkpoint = torch.load(args.weights, map_location='cpu', weights_only=True)
    model.load_state_dict(checkpoint['model'], strict=True)
    tensor, ratio = preproc.preproc(image, (args.size, args.size))
    with torch.inference_mode():
        prediction = model(torch.from_numpy(tensor).unsqueeze(0))
        output = postprocess(prediction, 80, conf_thre=0.25, nms_thre=0.45, class_agnostic=True)[0]
    detections = []
    if output is not None:
        for row in output.tolist():
            detections.append({'class_id': int(row[6]), 'score': row[4]*row[5],
                               'xyxy_original': [x/ratio for x in row[:4]]})
    result = {'mode': 'PC CPU FP32 reference only; no FPGA or INT8 execution',
              'model': args.model,
              'upstream_commit': PIN, 'weights_sha256': hashlib.sha256(args.weights.read_bytes()).hexdigest(),
              'image_sha256': hashlib.sha256(args.image.read_bytes()).hexdigest(),
              'torch': torch.__version__, 'opencv': cv2.__version__,
              'input_size': args.size, 'original_hw': list(image.shape[:2]),
              'preprocess': 'official non-legacy BGR, top-left resize, pad=114, CHW, no /255',
              'confidence': 0.25, 'nms_iou': 0.45, 'class_agnostic_nms': True,
              'detections': detections}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(f'PASS PC reference: {len(detections)} detections -> {args.output}')


if __name__ == '__main__':
    main()

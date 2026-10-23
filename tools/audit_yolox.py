#!/usr/bin/env python3
"""Profile the pinned official Nano graph on CPU; no weights or accuracy claim."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

PIN = '6ddff4824372906469a7fae2dc3206c7aa4bbaee'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    source = args.source.resolve()
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != PIN:
        p.error(f'expected upstream commit {PIN}, got {commit}')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        p.error('upstream checkout must be clean')
    sys.path.insert(0, str(source))
    import torch
    from yolox.exp import get_exp
    torch.set_num_threads(2)
    torch.manual_seed(20261023)
    model = get_exp(None, 'yolox-nano').get_model().eval()
    model.head.decode_in_inference = False
    profiles = []
    for size in [320, 416]:
        records = []

        def hook(name):
            def record(module, inputs, output):
                kernel = module.kernel_size[0] * module.kernel_size[1]
                macs = output.numel() * (module.in_channels // module.groups) * kernel
                kind = ('depthwise' if module.groups == module.in_channels and module.groups > 1
                        else 'pointwise' if kernel == 1 else 'regular_spatial')
                records.append({'name': name, 'kind': kind, 'input': list(inputs[0].shape),
                                'output': list(output.shape), 'kernel': list(module.kernel_size),
                                'stride': list(module.stride), 'groups': module.groups,
                                'weight_elements': module.weight.numel(), 'macs': macs})
            return record

        handles = [m.register_forward_hook(hook(n)) for n, m in model.named_modules()
                   if isinstance(m, torch.nn.Conv2d)]
        with torch.inference_mode():
            output = model(torch.zeros(1, 3, size, size))
        for handle in handles:
            handle.remove()
        macs = Counter()
        for row in records:
            macs[row['kind']] += row['macs']
        profiles.append({'size': size, 'output_shape': list(output.shape),
                         'input_u8_bytes': 3*size*size, 'conv_macs': sum(macs.values()),
                         'conv_macs_by_kind': dict(macs),
                         'largest_conv_output_elements': max(torch.tensor(x['output']).prod().item() for x in records),
                         'layers': records})
    source_files = ['exps/default/yolox_nano.py', 'yolox/models/network_blocks.py',
                    'yolox/models/yolo_head.py', 'yolox/models/yolo_pafpn.py',
                    'yolox/models/darknet.py', 'yolox/data/data_augment.py']
    report = {'upstream': 'https://github.com/Megvii-BaseDetection/YOLOX',
              'commit': commit, 'torch': torch.__version__,
              'mode': 'CPU eval, synthetic zeros, random weights; shape/MAC audit only',
              'parameters': sum(x.numel() for x in model.parameters()),
              'conv_weight_elements': sum(m.weight.numel() for m in model.modules() if isinstance(m, torch.nn.Conv2d)),
              'module_counts': dict(Counter(type(m).__name__ for m in model.modules())),
              'source_sha256': {f: hashlib.sha256((source/f).read_bytes()).hexdigest() for f in source_files},
              'profiles': profiles}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ['profiles', 'source_sha256', 'module_counts']}, indent=2))
    for item in profiles:
        print({k: v for k, v in item.items() if k != 'layers'})


if __name__ == '__main__':
    main()

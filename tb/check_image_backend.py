#!/usr/bin/env python3
"""Exercise image transport, halo stitching and all output/input channel tails."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from adam_image_backend import AdamSimulator, MAGIC, REQUEST


def reference(image, weight, stride, pad):
    ci, h, w = image.shape
    co, _, k, _ = weight.shape
    oh, ow = (h+2*pad-k)//stride+1, (w+2*pad-k)//stride+1
    padded = np.pad(image.astype(np.int64), ((0, 0), (pad, pad), (pad, pad)))
    result = np.zeros((co, oh, ow), dtype=np.int64)
    for ky in range(k):
        for kx in range(k):
            patch = padded[:, ky:ky+oh*stride:stride, kx:kx+ow*stride:stride]
            result += np.einsum('ci,iyx->cyx', weight[:, :, ky, kx].astype(np.int64), patch)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulator', type=Path, default=Path('build/image-cosim/obj/Vadam_conv128'))
    parser.add_argument('--output', type=Path, default=Path('build/image-cosim/backend-test.json'))
    args = parser.parse_args()
    rng = np.random.default_rng(20261023)
    cases = [(23, 29, 17, 33, k, s, k//2) for k in (1, 3) for s in (1, 2)]
    cases += [(7, 9, 768, 17, 3, 2, 0), (1, 1, 1, 1, 1, 1, 0),
              (17, 17, 3, 5, 3, 1, 1), (3, 3, 8, 16, 3, 1, 1)]
    results = []
    for verify in (True, False):
        with AdamSimulator(args.simulator, verify=verify) as simulator:
            for index, (h, w, ci, co, k, stride, pad) in enumerate(cases):
                image = rng.integers(-128, 128, (ci, h, w), dtype=np.int8)
                weights = rng.integers(-128, 128, (co, ci, k, k), dtype=np.int8)
                if index == 6:
                    image.fill(-128); weights.fill(-128)
                if index == 7:
                    image.fill(127); weights.fill(-128)
                actual, stats = simulator.conv(image, weights, stride, pad)
                np.testing.assert_array_equal(actual, reference(image, weights, stride, pad))
                oh, ow = actual.shape[1:]
                expected_steps = ((co+15)//16)*oh*ow*((ci+7)//8)*k*k
                assert stats['rtl_mac_steps'] == expected_steps
                assert stats['scalar_checked_values'] == (actual.size if verify else 0)
                results.append({'shape_hw_ci_co_k_s_p': list(cases[index]), 'verify': verify, **stats})
    invalid = [struct.pack('<I', 0), REQUEST.pack(MAGIC, 1, 0, 3, 1, 1, 3, 1, 1, 1),
               REQUEST.pack(MAGIC, 1, 3, 3, 769, 1, 3, 1, 1, 1),
               REQUEST.pack(MAGIC, 1, 1, 1, 1, 1, 1, 1, 0, 1)]
    for payload in invalid:
        failed = subprocess.run([str(args.simulator.resolve())], input=payload, capture_output=True, timeout=5)
        assert failed.returncode == 1 and b'adam_image_server:' in failed.stderr
        assert not failed.stdout, 'failed request must not produce an output tensor'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {'result': 'PASS', 'convolutions': len(results), 'invalid_requests': len(invalid),
              'independent_reference': 'NumPy INT64 einsum across channels, untiled feature map',
              'output_values_compared': sum(r['output_values'] for r in results), 'cases': results}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(f'PASS image transport: {len(results)} convolutions, {result["output_values_compared"]} '
          f'values, {len(invalid)} invalid requests')


if __name__ == '__main__':
    main()

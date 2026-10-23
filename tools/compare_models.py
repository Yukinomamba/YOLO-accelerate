#!/usr/bin/env python3
"""Summarize measured graphs and explicitly idealized storage/compute bounds."""
import argparse
import hashlib
import json
from pathlib import Path


def summarize(path, expected):
    raw = path.read_bytes()
    audit = json.loads(raw)
    if audit['model'] != expected:
        raise ValueError(f'expected {expected}, got {audit["model"]}')
    profiles = []
    for profile in audit['profiles']:
        layers = profile['layers']
        if sum(layer['macs'] for layer in layers) != profile['conv_macs']:
            raise ValueError('layer MAC sum differs from profile total')
        profiles.append({
            **{k: v for k, v in profile.items() if k != 'layers'},
            'conv_calls': len(layers),
            'depthwise_calls': sum(x['kind'] == 'depthwise' for x in layers),
            'ideal_conv_ms_at_100mhz': {
                str(macs): profile['conv_macs'] / (macs * 100_000)
                for macs in (64, 128, 256)
            },
            'uart_8n1_payload_seconds': {
                str(baud): profile['input_u8_bytes'] * 10 / baud
                for baud in (115200, 921600, 3000000)
            },
        })
    return {
        'model': audit['model'], 'commit': audit['commit'], 'torch': audit['torch'],
        'mode': audit['mode'], 'audit_sha256': hashlib.sha256(raw).hexdigest(),
        'source_sha256': audit['source_sha256'], 'parameters': audit['parameters'],
        'conv_int8_weight_bytes': audit['conv_weight_elements'],
        'conv_int8_weight_mib': audit['conv_weight_elements'] / 2**20,
        'folded_conv_bias_int32_bytes_assumption': audit['conv_output_channels_sum'] * 4,
        'per_channel_scale_fp32_bytes_assumption': audit['conv_output_channels_sum'] * 4,
        'profiles': profiles,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--nano', type=Path, required=True)
    p.add_argument('--tiny', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    nano = summarize(args.nano, 'yolox-nano')
    tiny = summarize(args.tiny, 'yolox-tiny')
    if nano['commit'] != tiny['commit']:
        p.error('model audits must use the same upstream commit')
    if [x['size'] for x in nano['profiles']] != [x['size'] for x in tiny['profiles']]:
        p.error('model audits must cover the same input sizes')
    report = {
        'models': [nano, tiny],
        'tiny_over_nano_conv_weight_ratio': tiny['conv_int8_weight_bytes'] / nano['conv_int8_weight_bytes'],
        'tiny_over_nano_conv_mac_ratio_by_size': {
            str(t['size']): t['conv_macs'] / n['conv_macs']
            for n, t in zip(nano['profiles'], tiny['profiles'])
        },
        'limits': [
            'Graph profiling uses random weights, not accuracy evaluation.',
            'INT8 storage is projected before packing, alignment, LUTs and descriptors.',
            'Largest convolution output is not peak live feature memory.',
            'Compute bounds assume full MAC utilization; omit DMA, activation and CPU work.',
            '100 MHz is a scenario, not a Pango timing result.',
            'UART bounds omit framing, ACKs and retries beyond the 8N1 byte format.',
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'PASS two-model comparison -> {args.output}')


if __name__ == '__main__':
    main()

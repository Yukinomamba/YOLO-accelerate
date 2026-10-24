#!/usr/bin/env python3
"""Collect current-source functional, cycle-profile and routed evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=Path('build/throughput'))
    parser.add_argument('--implementation', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('use a fresh output path')
    build = args.build_dir
    def read(path):
        return json.loads(path.read_text())
    adam, npu, image_manifest, image, mapped = map(read, [build/'adam/summary-all.json',
        build/'npu/summary.json', build/'image/manifest.json', build/'image-test.json', build/'netlist/summary.json'])
    physical, profile = map(read, [args.implementation, args.profile])
    hashes = {}
    for source in (adam, npu, image_manifest):
        for name, expected in source['source_sha256'].items():
            assert digest(ROOT/name) == expected, f'stale result: {name}'
            hashes[name] = expected
    assert image_manifest['build_driver_sha256'] == digest(ROOT/'tools/build_image_sim.py')
    assert digest(build/'image/obj/Vadam_conv128') == image_manifest['binary_sha256']
    assert mapped['status'] == physical['status'] == profile['status'] == image['result'] == 'PASS'
    assert mapped['netlist_sha256'] == physical['netlist_comparison']['regenerated_sha256']
    assert physical['functional_validation'] == mapped
    assert mapped['test_sha256'] == digest(ROOT/'tb/npu_measure_top.cpp')
    assert profile['test_sha256'] == digest(ROOT/'tb/npu_profile.cpp')
    assert profile['profile_driver_sha256'] == digest(ROOT/'tools/profile_npu.py')
    assert profile['comparison_driver_sha256'] == digest(ROOT/'tools/compare_npu_profiles.py')
    for name, expected in profile['tile_evidence'][1]['source_sha256'].items():
        assert digest(ROOT/name) == hashes[name] == physical['source_sha256'][name] == expected
    third = read(ROOT/'third_party/adamgallas/manifest.json')
    for name, item in third['files'].items():
        assert digest(ROOT/'third_party/adamgallas'/name) == item['sha256']
    results = []
    for suite in (adam, npu):
        for case in suite['results']:
            assert case['result'].startswith('PASS ')
            results.append(case)
    for name in ['tb/check_image_backend.py', 'tools/adam_image_backend.py', 'tb/npu_profile.cpp',
                 'tools/profile_npu.py', 'tools/compare_npu_profiles.py', 'tools/build_image_sim.py',
                 'tools/pango/check_netlist.py', 'tools/pango/compact_trace.py',
                 'tools/pango/stage_implementation.py', 'tools/pango/collect_implementation.py',
                 'tb/check_implementation_report.py', 'tools/collect_throughput_validation.py']:
        hashes[name] = digest(ROOT/name)
    evidence = [build/'adam/summary-all.json', build/'npu/summary.json', build/'image/manifest.json',
                build/'image-test.json', build/'image-test.metrics.json', build/'netlist/summary.json',
                build/'baseline-profile/summary.json', build/'optimized-profile/summary.json',
                args.implementation, args.profile]
    report = {'schema': 'npu128-throughput-validation-v1', 'date': '2026-10-24', 'status': 'PASS',
              'source_branch': subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip(),
              'source_base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'source_identity_note': 'Changes were uncommitted during measurement; source hashes identify the exact tested implementation.',
              'verilator': npu['verilator'], 'source_sha256': hashes, 'rtl_results': results,
              'mac_structure': adam['structure'],
              'upstream_byte_integrity': {'status': 'PASS', 'files': len(third['files'])},
              'image_transport': image, 'image_transport_metrics': read(build/'image-test.metrics.json'),
              'mapped_functional': mapped,
              'physical': {key: physical[key] for key in ('status', 'project', 'clock_period_ns', 'device',
                  'routed_fmax', 'routed_setup', 'routed_hold', 'resources')},
              'cycle_contract': {'mac_latency_edges': 7, 'address_stages': 5, 'postprocess_stages': 6,
                  'result_slots': 2, 'credit_invariant': 'queued results + in-flight pixels <= 2',
                  'no_stall_reference': 'software/adam128_cycle_model.h; direct-convolution sink only'},
              'evidence_sha256': {str(p): digest(p) for p in evidence},
              'route_run': True, 'board_run': False, 'full_yolox_accuracy_rerun': False,
              'limitations': ['Standalone measurement harness, automatic IO placement; no integrated CPU/DDR/PLL timing.',
                  'Gate replay compresses serial shifts and omits performance-counter comparison; no SDF.',
                  'Profiles measure representative zero-data tiles weighted by recorded model shapes, not end-to-end inference.',
                  'Local-port load costs exclude CPU, DDR/DMA, non-convolution operators, communication and coefficient configuration.']}
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print('PASS current-source RTL/image/mapped/profile/routed evidence; upstream byte integrity intact')


if __name__ == '__main__':
    main()

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
    prefetch = profile['schema'] == 'npu128-prefetch-profile-v1'
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
    if prefetch:
        assert profile['profile_driver_sha256'] == digest(ROOT/'tools/profile_prefetch.py')
        assert profile['binary_sha256'] == digest(build/'npu/prefetch/Vnpu_conv128')
        profiled_sources = profile['source_sha256']
        for row in profile['comparisons']:
            assert row['serial']['cycles']-row['prefetch']['cycles'] == row['prefetch']['overlap_writes']
    else:
        assert profile['test_sha256'] == digest(ROOT/'tb/npu_profile.cpp')
        assert profile['profile_driver_sha256'] == digest(ROOT/'tools/profile_npu.py')
        assert profile['comparison_driver_sha256'] == digest(ROOT/'tools/compare_npu_profiles.py')
        profiled_sources = profile['tile_evidence'][1]['source_sha256']
    for name, expected in profiled_sources.items():
        assert digest(ROOT/name) == hashes[name] == expected
        if name.startswith('rtl/'):
            assert physical['source_sha256'][name] == expected
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
                args.implementation, args.profile]
    if prefetch:
        evidence += [build/'profile/summary.json', build/'profile/workloads.txt', build/'profile/run.log']
        for name in ('tools/profile_prefetch.py', 'tools/pango/stage.py',
                     'config/board-budget.json', 'config/yolox-tiny.lock.json'):
            hashes[name] = digest(ROOT/name)
    else:
        evidence += [build/'baseline-profile/summary.json', build/'optimized-profile/summary.json']
    report = {'schema': 'npu128-prefetch-validation-v1' if prefetch else 'npu128-throughput-validation-v1',
              'date': '2026-10-24', 'status': 'PASS',
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
                  'Profiles execute recorded model tile shapes with zero data, not end-to-end inference.',
                  'Local-port load costs exclude CPU, DDR/DMA, non-convolution operators, communication and coefficient configuration.']}
    if prefetch:
        budget = read(ROOT/'config/board-budget.json')['engineering_targets_not_measurements']
        npu_resource = physical['resources']['u_npu(npu_conv128)']
        assert npu_resource['DRM'] <= budget['npu_drm36k_ceiling']
        assert npu_resource['LUT'] <= budget['npu_lut6_ceiling']
        assert npu_resource['APM'] <= budget['npu_apm_ceiling']
        prior_path = ROOT/'reports/npu128-throughput-validation.json'
        previous = read(prior_path)['image_transport']['cases']
        assert len(previous) == len(image['cases'])
        comparisons = []
        for old, new in zip(previous, image['cases']):
            for key in ('shape_hw_ci_co_k_s_p', 'verify', 'rtl_mac_steps', 'rtl_active_cycles',
                        'tile_commands', 'output_values', 'output_int32_sha256'):
                assert old[key] == new[key], (old['shape_hw_ci_co_k_s_p'], key)
            multi = old['tile_commands'] > (old['shape_hw_ci_co_k_s_p'][3]+15)//16
            assert new['rtl_clock_cycles'] < old['rtl_clock_cycles'] if multi else new['rtl_clock_cycles'] == old['rtl_clock_cycles']
            comparisons.append({'shape_hw_ci_co_k_s_p': old['shape_hw_ci_co_k_s_p'], 'verify': old['verify'],
                'before_cycles': old['rtl_clock_cycles'], 'after_cycles': new['rtl_clock_cycles'],
                'output_int32_sha256': new['output_int32_sha256']})
        report['image_transport_comparison'] = {'baseline_sha256': digest(prior_path),
            'status': 'PASS', 'cases': comparisons, 'scope': 'same seeded nonzero tensors, bit-identical outputs and unchanged active/MAC cycles'}
        report['activation_buffers'] = {'banks': 2, 'words_per_bank': 24576, 'word_bits': 64,
            'busy_write_rule': 'only the inactive bank accepts writes; the NPU protects its active bank through final postprocess delivery'}
        report['engineering_budget'] = {'status': 'PASS', 'drm36k_ceiling': budget['npu_drm36k_ceiling'],
            'lut_ceiling': budget['npu_lut6_ceiling'], 'apm_ceiling': budget['npu_apm_ceiling'],
            'scope': 'repository NPU planning ceilings; not current integrated SoC free-resource measurements'}
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print('PASS current-source RTL/image/mapped/profile/routed evidence; upstream byte integrity intact')


if __name__ == '__main__':
    main()

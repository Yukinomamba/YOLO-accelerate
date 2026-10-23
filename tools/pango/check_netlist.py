#!/usr/bin/env python3
"""Check a mapped GTP netlist using Verilator or four-state Icarus pin replay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--pds-home', type=Path, default=os.environ.get('PDS_HOME'))
    parser.add_argument('--build-dir', type=Path, default=Path('build/npu128/netlist'))
    parser.add_argument('--rss-mib', type=int, default=2048)
    parser.add_argument('--as-mib', type=int, default=3072)
    parser.add_argument('--seconds', type=int, default=1200)
    parser.add_argument('--engine', choices=['iverilog', 'verilator'], default='iverilog')
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    parser.add_argument('--ivl-base', type=Path, help='optional extracted Icarus lib/ivl directory')
    parser.add_argument('--rtl-executable', type=Path, default=Path('build/npu128/measure/Vnpu_measure_top'))
    parser.add_argument('--full-pin-replay', action='store_true', help='include every serial shift (very slow with GTP RAM models)')
    args = parser.parse_args()
    if not args.pds_home:
        parser.error('set PDS_HOME or pass --pds-home')
    vendor = args.pds_home.resolve()/'arch/vendor/pango/verilog/simulation'
    netlist = args.project.resolve()/'prj_tasks/syn_1/synthesize/npu_measure_top_syn.vm'
    build = (ROOT/args.build_dir).resolve()
    if not build.is_relative_to(ROOT/'build') or not netlist.is_file() or not vendor.is_dir():
        parser.error('missing netlist/vendor library, or build directory outside build/')
    build.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.project/'manifest.json').read_text())
    for path in manifest['rtl']:
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest() != manifest['files'][path]:
            parser.error(f'current RTL differs from synthesized input: {path}')
    steps = []
    if args.engine == 'verilator':
        command = ['verilator', '--cc', '--exe', '--build', '--timing', '-O0', '-j', '1', '--threads', '1',
                   '--output-split', '3000', '--output-split-cfuncs', '100', '-CFLAGS', '-O0 -g0',
                   '-Wno-fatal', '--top-module', 'npu_measure_top', '--Mdir', str(build/'obj'),
                   '-y', str(vendor), str(netlist), str(ROOT/'tb/npu_measure_top.cpp')]
        steps = [('build', command, None), ('run', [str(build/'obj/Vnpu_measure_top')], None)]
        marker = 'PASS npu_measure_top:'
    else:
        executable = (ROOT/args.rtl_executable).resolve()
        summary_path = executable.parent.parent/'summary.json'
        if not executable.is_file() or not summary_path.is_file():
            parser.error('run make npu-test first, or pass the matching --rtl-executable')
        summary = json.loads(summary_path.read_text())
        for path, expected in summary['source_sha256'].items():
            if hashlib.sha256((ROOT/path).read_bytes()).hexdigest() != expected:
                parser.error(f'RTL trace executable is stale; rerun npu-test: {path}')
        env = os.environ.copy()
        env['NPU_PIN_TRACE'] = str(build/'rtl-pins.hex')
        command = [args.iverilog]
        if args.ivl_base:
            command += ['-B', str(args.ivl_base)]
        replay_top = 'tb_npu_pin_replay' if args.full_pin_replay else 'tb_npu_transaction_replay'
        command += ['-g2012', '-y', str(vendor), '-s', replay_top, '-o', str(build/'mapped.vvp'),
                    str(netlist), str(ROOT/f'tb/{replay_top}.sv')]
        run = [args.vvp]
        if args.ivl_base:
            run += ['-M', str(args.ivl_base)]
        trace_name = 'rtl-pins.hex' if args.full_pin_replay else 'transactions.hex'
        run += [str(build/'mapped.vvp'), f'+TRACE={build}/{trace_name}']
        steps = [('rtl', [str(executable)], env)]
        if not args.full_pin_replay:
            steps.append(('compact', [sys.executable, str(ROOT/'tools/pango/compact_trace.py'),
                                      str(build/'rtl-pins.hex'), str(build/'transactions.hex')], None))
        steps += [('build', command, None), ('run', run, None)]
        marker = 'PASS mapped NPU pin replay:' if args.full_pin_replay else 'PASS mapped NPU transaction replay:'
    results = []
    for name, cmd, env in steps:
        proc = subprocess.run([sys.executable, str(ROOT/'tools/run_guarded.py'),
                               '--rss-mib', str(args.rss_mib), '--as-mib', str(args.as_mib), '--min-available-mib', '6144',
                               '--seconds', str(args.seconds), '--log', str(build/f'{name}.log'),
                               '--metrics', str(build/f'{name}.metrics.json'), '--', *cmd], cwd=ROOT, env=env)
        results.append(json.loads((build/f'{name}.metrics.json').read_text()))
        if proc.returncode:
            raise SystemExit(proc.returncode)
    run_log = (build/'run.log').read_text()
    if marker not in run_log or 'FAIL' in run_log or 'ERROR' in run_log or 'FATAL' in run_log:
        raise RuntimeError('netlist test PASS marker missing or vendor assertion failed')
    report = {'schema': 'npu128-mapped-functional-v1', 'status': 'PASS', 'engine': args.engine,
              'scope': 'functional GTP simulation, no SDF or routed timing',
              'netlist_sha256': hashlib.sha256(netlist.read_bytes()).hexdigest(),
              'test_sha256': hashlib.sha256((ROOT/'tb/npu_measure_top.cpp').read_bytes()).hexdigest(),
              'test_result': run_log.strip(), 'metrics': results}
    if args.engine == 'iverilog':
        report['pin_trace_sha256'] = hashlib.sha256((build/'rtl-pins.hex').read_bytes()).hexdigest()
        report['replay_test_sha256'] = hashlib.sha256((ROOT/f'tb/{replay_top}.sv').read_bytes()).hexdigest()
        report['serial_shifts_replayed'] = args.full_pin_replay
        report['performance_counters_compared'] = args.full_pin_replay
        if not args.full_pin_replay:
            report['compact_trace_sha256'] = hashlib.sha256((build/'transactions.hex').read_bytes()).hexdigest()
        models = {}
        with (build/'mapped.vvp').open() as source:
            for line in source:
                match = re.match(r'\s*"([^"]+\.v)";', line)
                if match:
                    path = Path(match.group(1)).resolve()
                    if path.is_relative_to(vendor) and path.is_file():
                        models[str(path.relative_to(vendor))] = hashlib.sha256(path.read_bytes()).hexdigest()
        report['gtp_model_sha256'] = models
    (build/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(run_log.strip())


if __name__ == '__main__':
    main()

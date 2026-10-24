#!/usr/bin/env python3
"""Four-state mapped byte-boundary replay; UART PHY remains covered by RTL pins."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from stage import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--pds-home', type=Path, required=True)
    parser.add_argument('--simulator', type=Path, required=True)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, required=True)
    args = parser.parse_args()
    build = (ROOT/args.build_dir).resolve()
    if not build.is_relative_to(ROOT/'build'):
        parser.error('use build/')
    build.mkdir(parents=True, exist_ok=True)
    digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    functional = json.loads(args.validation.read_text())
    assert functional['status'] == 'PASS' and functional['binary_sha256'] == digest(args.simulator)
    for name, expected in functional['source_sha256'].items(): assert digest(ROOT/name) == expected, name
    netlist = args.project/'prj_tasks/syn_1/synthesize/npu_uart_board_syn.vm'
    vendor = args.pds_home/'arch/vendor/pango/verilog/simulation'
    ivl = ROOT/'build/tools/iverilog/root/usr/lib/x86_64-linux-gnu/ivl'
    trace = build/'frames.hex'
    metrics = []

    def guarded(name, command):
        subprocess.run([sys.executable, str(ROOT/'tools/run_guarded.py'), '--rss-mib', '2048',
            '--as-mib', '3072', '--min-available-mib', '6144', '--seconds', '1200',
            '--log', str(build/f'{name}.log'), '--metrics', str(build/f'{name}.metrics.json'), '--', *map(str, command)],
            cwd=ROOT, check=True)
        metrics.append(json.loads((build/f'{name}.metrics.json').read_text()))

    guarded('trace', [sys.executable, ROOT/'tools/pango/uart_gate_trace.py', '--simulator', args.simulator, '--output', trace])
    guarded('build', [ROOT/'build/tools/iverilog/root/usr/bin/iverilog', '-B', ivl, '-g2012', '-y', vendor,
        '-s', 'tb_uart_byte_replay', '-o', build/'mapped.vvp', netlist, ROOT/'tb/tb_uart_byte_replay.sv'])
    guarded('run', [ROOT/'build/tools/iverilog/root/usr/bin/vvp', '-M', ivl, build/'mapped.vvp', f'+TRACE={trace}'])
    result = (build/'run.log').read_text().strip()
    assert 'PASS mapped UART byte replay:' in result and not any(x in result for x in ('FAIL', 'ERROR', 'FATAL'))
    models = {}
    with (build/'mapped.vvp').open() as source:
        for line in source:
            m = re.match(r'\s*"([^"]+\.v)";', line)
            if m:
                p = Path(m[1]).resolve()
                if p.is_relative_to(vendor.resolve()) and p.is_file(): models[str(p.relative_to(vendor.resolve()))] = digest(p)
    report = {'schema': 'npu128-uart-mapped-byte-v1', 'status': 'PASS', 'netlist_sha256': digest(netlist),
        'scope': 'GTP four-state byte bridge/MMIO/NPU replay; UART PHY serialization bypassed, no SDF',
        'result': result, 'metrics': metrics, 'trace_sha256': digest(trace),
        'test_sha256': digest(ROOT/'tb/tb_uart_byte_replay.sv'), 'gtp_model_sha256': models,
        'trace_driver_sha256': digest(ROOT/'tools/pango/uart_gate_trace.py'),
        'rtl_reference_sha256': digest(args.validation), 'board_run': False,
        'forced_boundary': ['RX valid/data/error', 'PHY transmitter busy=0'],
        'not_forced': 'bridge, MMIO, NPU, SRAM/APM, command/state/data outputs'}
    (build/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(result)


if __name__ == '__main__':
    main()

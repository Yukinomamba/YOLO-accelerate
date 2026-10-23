#!/usr/bin/env python3
"""Stage the complete byte-identical upstream engine, not the 128-MAC rewrite."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work-root', type=Path, default=os.environ.get('PDS_WORK_ROOT'))
    p.add_argument('--name', required=True)
    a = p.parse_args()
    if not a.work_root or not a.work_root.is_dir() or not re.fullmatch('[a-z0-9_-]+', a.name):
        p.error('existing Windows work root and safe fresh name required')
    target = a.work_root.resolve() / 'work' / a.name
    native = subprocess.check_output(['wslpath', '-w', str(target)], text=True).strip()
    if not re.match(r'^[A-Za-z]:\\', native) or target.exists() or not native.isascii():
        p.error('fresh native Windows drive directory required')
    origin = ROOT / 'third_party/adamgallas'
    upstream = json.loads((origin / 'manifest.json').read_text())
    for name, hashes in upstream['files'].items():
        assert hashlib.sha256((origin / name).read_bytes()).hexdigest() == hashes['sha256'], name
    rtl = sorted(str(f.relative_to(ROOT)) for f in (origin / 'source').glob('*.v'))
    rtl += ['rtl/upstream/adam_upstream.sv']
    header = (ROOT / rtl[-1]).read_text().split('\n);', 1)[0]
    ports = re.findall(r'\b(input|output)\s+(?:wire\s+)?(?:\[[^\]]+\]\s*)?(\w+)\s*(?:,|$)', header, re.M)
    assert len(ports) == 30, ports
    fdc = ['create_clock -name {clk} -period 10 -waveform {0 5} [get_ports {clk}]',
           'set_clock_uncertainty -setup 0.2 [get_clocks {clk}]',
           'set_clock_uncertainty -hold 0.05 [get_clocks {clk}]']
    for direction, name in ports:
        if name == 'clk':
            continue
        for bound, delay in [('min', 0), ('max', 1)]:
            # Wildcard includes every bit of bus ports as well as scalar ports.
            fdc.append(f'set_{direction}_delay -clock [get_clocks {{clk}}] -{bound} {delay} [get_ports {{{name}*}}]')
    tcl = ['set_arch -family Logos2 -device PG2L200H -package FBB676 -speedgrade -6',
           'set_option max_threads 1', *(f'add_design {{{x}}}' for x in rtl),
           'add_constraint {measurement.fdc}',
           'compile -top_module adam_upstream -verilog_standard SystemVerilog -loop_limit 65536',
           'synthesize -ads -selected_syn_tool_opt 2 -max_path 100 -nworst 3 '
           '-report_logic_level_distribution -report_exception TRUE']
    target.mkdir(parents=True)
    hashes = {}
    for name in [*rtl, 'third_party/adamgallas/LICENSE', 'third_party/adamgallas/manifest.json',
                 'tools/pango/stage_upstream.py', 'tools/pango/run_synthesis.ps1', 'tools/pango/GuardedJob.cs']:
        dst = target / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dst)
        hashes[name] = hashlib.sha256(dst.read_bytes()).hexdigest()
    for name, lines in [('measurement.fdc', fdc), ('synthesize.tcl', tcl)]:
        dst = target / name
        dst.write_text('\n'.join(lines) + '\n')
        hashes[name] = hashlib.sha256(dst.read_bytes()).hexdigest()
    manifest = dict(schema='adam-upstream-pango-v1', top='adam_upstream', rtl=rtl, files=hashes,
                    upstream_commit=upstream['commit'], upstream_modified_files=[],
                    source_base_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                    source_branch=subprocess.check_output(['git','branch','--show-current'],text=True).strip(),
                    device='PG2L200H-6IFBB676', clock_period_ns=10,
                    scope='Complete original 576-product engine, native ports, no board pinout or CPU',
                    project=f'$PDS_WORK_ROOT/work/{a.name}')
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('PASS staged original engine:', native)


if __name__ == '__main__':
    main()

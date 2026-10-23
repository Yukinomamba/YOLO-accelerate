#!/usr/bin/env python3
"""Verify immutable upstream RTL and execute its native CSR/AXIS interface."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build-dir', type=Path, default=Path('build/upstream-faithful/verified'))
    a = p.parse_args()
    b = a.build_dir
    b.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path('third_party/adamgallas/manifest.json').read_text())
    for name, entry in manifest['files'].items():
        path = Path('third_party/adamgallas') / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], name
    rtl = ['rtl/upstream/adam_upstream.sv'] + sorted(str(p) for p in Path('third_party/adamgallas/source').glob('*.v'))
    sources = rtl + ['software/adam_upstream_abi.h', 'tb/adam_upstream.cpp',
                     'tools/run_upstream_tests.py', 'tools/run_guarded.py']
    results = []
    def run(name, command):
        subprocess.run([sys.executable, 'tools/run_guarded.py', '--rss-mib', '2048',
                        '--as-mib', '3072', '--min-available-mib', '6144', '--seconds', '900',
                        '--log', str(b/(name+'.log')), '--metrics', str(b/(name+'.metrics.json')),
                        '--', *command], check=True)
        results.append(json.loads((b/(name+'.metrics.json')).read_text()))
    # Original warning diagnostics are retained. No source rewrite or blanket
    # "lint clean" claim; warnings from the new wrapper are rejected below.
    common = ['verilator', '-Wall', '-Wno-fatal', '--top-module', 'adam_upstream']
    run('structure', [*common, '--json-only', '--json-only-output', str(b/'model.json'),
                      '--json-only-meta-output', str(b/'model.meta.json'), *rtl])
    ast = json.loads((b/'model.json').read_text())
    modules = {m['name']: m for m in ast['modulesp'] if m['type']=='MODULE'}
    def nodes(value):
        if isinstance(value, dict):
            yield value
            for v in value.values(): yield from nodes(v)
        elif isinstance(value, list):
            for v in value: yield from nodes(v)
    def count(name):
        if name == 'cal_mult_int8_x2_dsp': return 1
        return sum(count(n['modName']) for n in nodes(modules[name]) if n.get('type')=='CELL')
    pairs = count('adam_upstream')
    assert pairs == 288, pairs
    run('build', [*common, '--cc', '--exe', '--build', '-j', '1', '--Mdir', str(b/'obj'),
                  '-CFLAGS', '-O0', *rtl, str(ROOT/'tb/adam_upstream.cpp')])
    for name in ['structure', 'build']:
        log = (b/(name+'.log')).read_text()
        assert not re.search(r'%Warning[^\n]*rtl/upstream/', log), 'new wrapper warning'
    run('run', [str(b/'obj/Vadam_upstream')])
    log = (b/'run.log').read_text()
    assert 'PASS original Accel_Conv:' in log
    run('rv32im-abi', ['riscv64-unknown-elf-gcc', '-march=rv32im', '-mabi=ilp32',
                       '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsyntax-only',
                       '-x', 'c', 'software/adam_upstream_abi.h'])
    report = dict(schema='adam-upstream-validation-v1', upstream_commit=manifest['commit'],
                  source_base_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                  branch=subprocess.check_output(['git','branch','--show-current'],text=True).strip(),
                  upstream_modified_files=[], upstream_files_verified=len(manifest['files']),
                  source_sha256={x:hashlib.sha256(Path(x).read_bytes()).hexdigest() for x in sources},
                  paired_multipliers=pairs, int8_products=2*pairs,
                  result=log.strip(), metrics=results,
                  limits=['AXIS output continuously ready', 'weight windows have no input bubbles',
                          'not full YOLOX inference', 'pooling not yet tested'],
                  board_run=False)
    (b/'summary.json').write_text(json.dumps(report,indent=2).replace(str(ROOT),'$REPO_ROOT')+'\n')
    print(log.strip())


if __name__ == '__main__':
    main()

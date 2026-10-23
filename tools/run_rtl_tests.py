#!/usr/bin/env python3
"""Build and run independent shapes; keep commands, source hashes and raw logs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--verilator', default='verilator')
    p.add_argument('--jobs', type=int, default=2)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    for key, directory in [('CCACHE_DIR', 'ccache'), ('CCACHE_TEMPDIR', 'ccache-tmp')]:
        path = root / 'build' / directory
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    files = ['rtl/systolic_pe.sv', 'rtl/systolic_tile.sv', 'tb/tb_systolic_tile.sv']
    summary = {'source_sha256': {f: hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files},
               'tool': subprocess.check_output([args.verilator, '--version'], text=True).strip(),
               'results': [], 'skip': 0}
    for rows, cols in [(1, 1), (2, 3), (4, 4), (8, 8)]:
        out = root / 'build' / 'sim' / f'{rows}x{cols}'
        out.mkdir(parents=True, exist_ok=True)
        cmd = [args.verilator, '--binary', '--timing', '-Wall', '-j', str(args.jobs),
               '--top-module', 'tb_systolic_tile', f'-GROWS={rows}', f'-GCOLS={cols}',
               '--Mdir', str(out), *files]
        (out / 'command.json').write_text(json.dumps(cmd, indent=2) + '\n')
        with (out/'compile.log').open('w') as log:
            subprocess.run(cmd, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run([str(out/'Vtb_systolic_tile')], cwd=root,
                                text=True, capture_output=True, timeout=60)
        (out/'run.log').write_text(result.stdout + result.stderr)
        result.check_returncode()
        if 'PASS systolic_tile' not in result.stdout:
            raise RuntimeError(f'No PASS for {rows}x{cols}')
        print(result.stdout.splitlines()[0])
        summary['results'].append({'rows': rows, 'cols': cols, 'gemm_cases': 101,
                                   'status': 'PASS', 'log': f'build/sim/{rows}x{cols}/run.log'})
    (root/'build/sim/summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()

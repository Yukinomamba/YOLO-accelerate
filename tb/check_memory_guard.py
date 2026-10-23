#!/usr/bin/env python3
"""Exercise the guard with small, owned child processes; allocate at most 32 MiB."""
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
out = root / 'build/adam128/guard-tests'
out.mkdir(parents=True, exist_ok=True)
checks = [
    ('limits', [],
     'import os,resource; assert len(os.sched_getaffinity(0))==1; '
     'assert os.nice(0)==19; assert resource.getrlimit(resource.RLIMIT_AS)==(2**30,2**30)', None),
    ('rss', ['--rss-mib', '16'],
     'import time; allocation=bytearray(32*2**20); time.sleep(2)',
     'own process group exceeded RSS cap'),
    ('address-space', ['--as-mib', '64'],
     'try:\n allocation=bytearray(128*2**20)\nexcept MemoryError:\n pass\nelse:\n raise RuntimeError("limit not enforced")', None),
    ('timeout', ['--seconds', '1'], 'import time; time.sleep(3)', 'timeout'),
]
results = []
for name, options, code, expected in checks:
    process = subprocess.run([sys.executable, str(root/'tools/run_guarded.py'), *options,
                              '--log', str(out/f'{name}.log'), '--metrics', str(out/f'{name}.json'),
                              '--', sys.executable, '-c', code], cwd=root)
    metrics = json.loads((out/f'{name}.json').read_text())
    assert metrics['guard_stop'] == expected, (name, metrics)
    assert process.returncode == (1 if expected else 0), (name, process.returncode)
    results.append({'name': name, 'status': 'PASS', 'expected_guard_stop': expected,
                    'sampled_process_group_peak_rss_bytes': metrics['sampled_process_group_peak_rss_bytes']})
(out/'summary.json').write_text(json.dumps(results, indent=2)+'\n')
print('PASS memory guard: affinity/nice, RSS shutdown, hard address-space limit, timeout')

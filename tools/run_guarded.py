#!/usr/bin/env python3
"""Run only our process group with bounded memory, one CPU and low priority."""
import argparse
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time


def available_bytes():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) * 1024
    raise RuntimeError('MemAvailable unavailable; refusing to start')


def group_rss(pgid):
    pages = 0
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            data = path.read_text()
            fields = data[data.rfind(')') + 2:].split()
            if int(fields[2]) == pgid:
                pages += int(fields[21])
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return pages * os.sysconf('SC_PAGE_SIZE')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--rss-mib', type=int, default=512)
    p.add_argument('--as-mib', type=int, default=1024)
    p.add_argument('--min-available-mib', type=int, default=2048)
    p.add_argument('--seconds', type=int, default=600)
    p.add_argument('--log', type=Path, required=True)
    p.add_argument('--metrics', type=Path, required=True)
    p.add_argument('command', nargs=argparse.REMAINDER)
    args = p.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or min(args.rss_mib, args.as_mib, args.min_available_mib, args.seconds) <= 0:
        p.error('a command and positive limits are required')
    initial_available = available_bytes()
    if initial_available < args.min_available_mib * 2**20:
        p.error('available Linux memory below reserve; no process started')
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(CCACHE_DISABLE='1', MAKEFLAGS='-j1', OMP_NUM_THREADS='1',
               OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')

    def limits():
        cap = args.as_mib * 2**20
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.nice(19)
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})

    start = time.monotonic()
    peak = 0
    minimum_available = initial_available
    reason = None
    with args.log.open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   env=env, start_new_session=True, preexec_fn=limits)
        try:
            while process.poll() is None:
                rss = group_rss(process.pid)
                free = available_bytes()
                peak = max(peak, rss)
                minimum_available = min(minimum_available, free)
                if rss > args.rss_mib * 2**20:
                    reason = 'own process group exceeded RSS cap'
                elif free < args.min_available_mib * 2**20:
                    reason = 'Linux available memory fell below reserve'
                elif time.monotonic() - start > args.seconds:
                    reason = 'timeout'
                if reason:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    break
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    metrics = {
        'command': command, 'returncode': process.returncode, 'guard_stop': reason,
        'elapsed_seconds': time.monotonic() - start,
        'sampled_process_group_peak_rss_bytes': peak,
        'minimum_linux_available_bytes': minimum_available,
        'rss_limit_mib': args.rss_mib, 'per_process_address_space_limit_mib': args.as_mib,
        'linux_reserve_mib': args.min_available_mib, 'cpu_affinity_count': 1, 'nice': 19,
        'sampling_period_seconds': 0.05,
        'limits': 'RSS is sampled, not a cgroup hard limit; Windows memory is not measured here.'
    }
    args.metrics.write_text(json.dumps(metrics, indent=2) + '\n')
    print(f'{"PASS" if process.returncode == 0 and not reason else "FAIL"} '
          f'{command[0]}: sampled group RSS {peak/2**20:.1f} MiB, '
          f'{metrics["elapsed_seconds"]:.2f}s; log={args.log}')
    if reason or process.returncode:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

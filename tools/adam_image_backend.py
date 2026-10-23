#!/usr/bin/env python3
"""Versioned binary transport to the Verilator process; no software fallback."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAGIC = 0x314D4441
REQUEST = struct.Struct('<10I')
RESPONSE = struct.Struct('<II6Q')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class AdamSimulator:
    def __init__(self, binary, verify=True, stderr_path=None):
        self.binary = Path(binary).resolve()
        manifest_path = self.binary.parent.parent / 'manifest.json'
        self.manifest = json.loads(manifest_path.read_text())
        if sha256(self.binary) != self.manifest['binary_sha256']:
            raise ValueError('simulator binary differs from build manifest; rebuild it')
        for name, expected in self.manifest['source_sha256'].items():
            if sha256(ROOT / name) != expected:
                raise ValueError(f'simulator source changed since build: {name}; rebuild it')
        self.verify = verify
        self.sequence = 0
        self.stderr_path = Path(stderr_path or self.binary.parent.parent / 'server.log')
        self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self.stderr = self.stderr_path.open('w')
        self.process = subprocess.Popen([str(self.binary)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.stderr)

    def read(self, length):
        data = self.process.stdout.read(length)
        if len(data) != length:
            raise RuntimeError(f'simulator response truncated; inspect {self.stderr_path}')
        return data

    def conv(self, image, weights, stride=1, pad=0):
        import numpy as np
        if image.dtype != np.int8 or weights.dtype != np.int8 or image.ndim != 3 or weights.ndim != 4:
            raise ValueError('transport requires INT8 CHW activations and OIHW weights')
        ci, h, w = image.shape
        co, weight_ci, kh, kw = weights.shape
        if not (weight_ci == ci and kh == kw and kh in (1, 3) and stride in (1, 2) and
                0 <= pad <= kh//2 and 1 <= ci <= 768 and 1 <= co <= 768 and
                1 <= h <= 416 and 1 <= w <= 416 and h+2*pad >= kh and w+2*pad >= kh):
            raise ValueError('convolution is outside the adam128 image transport contract')
        oh, ow = (h+2*pad-kh)//stride+1, (w+2*pad-kh)//stride+1
        if max(image.size, weights.size, co*oh*ow) > 8*1024*1024:
            raise ValueError('tensor exceeds transport memory bound')
        self.sequence += 1
        self.process.stdin.write(REQUEST.pack(MAGIC, self.sequence, w, h, ci, co, kh, stride, pad, int(self.verify)))
        self.process.stdin.write(image.tobytes(order='C'))
        self.process.stdin.write(weights.tobytes(order='C'))
        self.process.stdin.flush()
        magic, sequence, count, cycles, mac_steps, active, tiles, checked = RESPONSE.unpack(self.read(RESPONSE.size))
        if (magic, sequence, count, checked) != (MAGIC, self.sequence, co*oh*ow, co*oh*ow if self.verify else 0):
            raise RuntimeError('simulator response identity, shape or verification count mismatch')
        output = np.frombuffer(self.read(count*4), dtype='<i4').reshape(co, oh, ow)
        stats = {'rtl_clock_cycles': cycles, 'rtl_mac_steps': mac_steps, 'rtl_active_cycles': active,
                 'tile_commands': tiles, 'output_values': count, 'scalar_checked_values': checked,
                 'output_int32_sha256': hashlib.sha256(output.tobytes()).hexdigest()}
        return output, stats

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type:
                self.process.terminate()
            else:
                self.process.stdin.close()
            try:
                code = self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
                if exc_type is None:
                    raise RuntimeError('simulator did not exit after EOF')
            if exc_type is None and code:
                raise RuntimeError(f'simulator failed with status {code}; inspect {self.stderr_path}')
        finally:
            self.process.stdout.close()
            if not self.process.stdin.closed:
                self.process.stdin.close()
            self.stderr.close()

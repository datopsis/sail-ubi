#!/usr/bin/env python3
"""Prove bundle admission rejects missing, extra and changed input bytes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path('scripts').resolve()))
from locklib import ROOT, read_lock, verify_bundle

arch = sys.argv[1]
root = ROOT / '.artifact-bundle' / arch
verify_bundle(root, arch)
wheel = root / 'wheel' / read_lock('sail.lock.json')['architectures'][arch]['wheel']['filename']


def rejects():
    try:
        verify_bundle(root, arch)
    except (ValueError, FileNotFoundError):
        return
    raise AssertionError('tampered bundle accepted')


extra = root / 'unexpected'
try:
    extra.write_text('unexpected')
    rejects()
finally:
    extra.unlink()
backup = wheel.with_suffix('.backup')
wheel.rename(backup)
try:
    rejects()
finally:
    backup.rename(wheel)
with wheel.open('r+b') as stream:
    original = stream.read(1)
    stream.seek(0)
    stream.write(bytes([original[0] ^ 1]))
try:
    rejects()
finally:
    with wheel.open('r+b') as stream:
        stream.write(original)
verify_bundle(root, arch)
print(arch, 'missing, extra and digest tampering rejected')

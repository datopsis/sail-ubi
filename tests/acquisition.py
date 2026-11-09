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

# Cryptographic verification must reject the wrong release identity even when
# the wheel's digest is correct. Parsing the certificate alone is insufficient.
import json
from pypi_attestations import Attestation, Distribution, VerificationError
from sigstore.verify.policy import Identity

provenance = json.loads((root / 'provenance.json').read_text())
attestation = Attestation.model_validate(provenance['attestation_bundles'][0]['attestations'][0])
try:
    attestation.verify(identity=Identity(identity='https://github.com/other/publisher',
                                        issuer='https://token.actions.githubusercontent.com'),
                       dist=Distribution.from_file(wheel))
except VerificationError:
    pass
else:
    raise AssertionError('incorrect publisher identity accepted')
print(arch, 'incorrect publisher identity rejected')

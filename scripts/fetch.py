#!/usr/bin/env python3
"""Acquire exact inputs and verify digests, NEVRA, RPM signatures and PyPI identity."""
import argparse
import json
import subprocess
import tempfile
import urllib.request

from locklib import ROOT, inputs, read_lock, verify, verify_bundle
from pypi_attestations import Attestation, Distribution
from sigstore.verify.policy import Identity


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)


def signatures(directory, arch):
    lock = read_lock('sail.lock.json')
    with tempfile.TemporaryDirectory() as db:
        for key in lock['rpm_keys']:
            path = directory / 'keys' / key['filename']
            details = run('gpg', '--batch', '--with-colons', '--show-keys', str(path))
            fingerprints = [line.split(':')[9] for line in details.splitlines() if line.startswith('fpr:')]
            if fingerprints != [key['fingerprint']]:
                raise ValueError('unexpected RPM key fingerprint')
            run('rpm', '--dbpath', db, '--import', str(path))
        for p in read_lock('rpms.lock.json')['architectures'][arch]:
            path = str(directory / 'rpms' / p['filename'])
            actual = run('rpm', '-qp', '--qf', '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\t%{SOURCERPM}', path)
            # rpm writes NOKEY warnings while querying a header against the host database.
            if actual.splitlines()[-1] != p['nevra'] + '\t' + p['source_rpm']:
                raise ValueError('RPM metadata mismatch: ' + path)
            result = run('rpmkeys', '--dbpath', db, '--checksig', path)
            if 'digests signatures OK' not in result:
                raise ValueError('RPM signature verification failed: ' + result)
    wheel = directory / 'wheel' / lock['architectures'][arch]['wheel']['filename']
    provenance = json.loads((directory / 'provenance.json').read_text())
    attestations = [a for b in provenance['attestation_bundles'] for a in b['attestations']]
    if not attestations:
        raise ValueError('publisher attestation missing')
    for a in attestations:
        Attestation.model_validate(a).verify(identity=Identity(**lock['publisher']), dist=Distribution.from_file(wheel))
    print(f'{arch}: verified all RPM signatures and Sail publisher attestation', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch', required=True, choices=['amd64', 'arm64'])
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    directory = ROOT / '.artifact-bundle' / args.arch
    if not args.verify_only:
        for name, entry in inputs(args.arch).items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                with urllib.request.urlopen(entry['url'], timeout=120) as response:
                    path.write_bytes(response.read())
            verify(path, entry)
    verify_bundle(directory, args.arch)
    signatures(directory, args.arch)


if __name__ == '__main__':
    main()

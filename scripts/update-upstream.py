#!/usr/bin/env python3
"""Propose upstream/base pins; review output, then resolve RPMs and fetch/verify."""
import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path


def get(url, accept=None):
    request = urllib.request.Request(url, headers={'Accept': accept} if accept else {})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def artifact(url):
    data = get(url)
    return {'url': url, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default='0.7.3')
    args = parser.parse_args()
    version = args.version
    metadata = json.loads(get(f'https://pypi.org/pypi/pysail/{version}/json'))
    ref = json.loads(subprocess.check_output(['gh', 'api', f'repos/lakehq/sail/git/ref/tags/v{version}']))['object']
    if ref['type'] != 'commit':
        raise ValueError('expected a lightweight upstream release tag')
    commit = ref['sha']
    lock = {'schema_version': 1, 'version': version, 'commit': commit,
            'license': 'Apache-2.0', 'base_images': {}, 'base_manifests': {},
            'publisher': {'identity': f'https://github.com/lakehq/sail/.github/workflows/release.yml@refs/tags/v{version}',
                          'issuer': 'https://token.actions.githubusercontent.com'},
            'architectures': {}}
    for role, variant in [('builder', 'minimal'), ('runtime', 'micro')]:
        raw = get(f'https://registry.access.redhat.com/v2/ubi9/ubi-{variant}/manifests/9.8',
                  'application/vnd.docker.distribution.manifest.list.v2+json')
        manifests = {m['platform']['architecture']: m['digest'] for m in json.loads(raw)['manifests']}
        assert {'amd64', 'arm64'} <= manifests.keys()
        digest = hashlib.sha256(raw).hexdigest()
        lock['base_images'][role] = f'registry.access.redhat.com/ubi9/ubi-{variant}:9.8@sha256:{digest}'
        lock['base_manifests'][role] = {a: manifests[a] for a in ['amd64', 'arm64']}
    for arch, suffix in [('amd64', 'manylinux2014_x86_64.manylinux_2_17_x86_64.whl'),
                         ('arm64', 'manylinux_2_24_aarch64.whl')]:
        wheel = next(x for x in metadata['urls'] if x['filename'].endswith(suffix))
        filename = wheel['filename']
        lock['architectures'][arch] = {'wheel': dict(filename=filename, url=wheel['url'],
                                                   sha256=wheel['digests']['sha256'], size=wheel['size']),
                                       'provenance': artifact(f'https://pypi.org/integrity/pysail/{version}/{filename}/provenance')}
    lock['source'] = {}
    for name in ['Cargo.lock', 'LICENSE']:
        lock['source'][name] = artifact(f'https://raw.githubusercontent.com/lakehq/sail/{commit}/{name}')
    lock['rpm_keys'] = []
    for key, fingerprint in [('fd431d51', '567E347AD0044ADE55BA8A5F199E2F91FD431D51'),
                             ('5a6340b3', '7E4624258C406535D56D6F135054E4A45A6340B3')]:
        lock['rpm_keys'].append(dict(artifact(f'https://security.access.redhat.com/data/{key}.txt'),
                                     filename=key+'.txt', fingerprint=fingerprint))
    Path('artifacts/sail.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    print('Proposed upstream/base pins. Run resolve-rpms.py, render-lock.py, and fetch.py; review all changes.')


if __name__ == '__main__':
    main()

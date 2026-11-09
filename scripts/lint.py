#!/usr/bin/env python3
"""Repository invariants, pinned workflows and synchronized build locks."""
import json
import re
import subprocess
from pathlib import Path

import yaml

subprocess.run(['python', 'scripts/render-lock.py', '--check'], check=True)
lock = json.loads(Path('artifacts/sail.lock.json').read_text())
assert lock['version'] in Path('Containerfile').read_text()
assert set(lock['architectures']) == {'amd64', 'arm64'}
for role in ['builder', 'runtime']:
    assert set(lock['base_manifests'][role]) == {'amd64', 'arm64'}
for arch, packages in json.loads(Path('artifacts/rpms.lock.json').read_text())['architectures'].items():
    assert len({p['nevra'] for p in packages}) == len(packages)
    for p in packages:
        assert re.fullmatch('[0-9a-f]{64}', p['sha256'])
        assert p['url'].startswith('https://cdn-ubi.redhat.com/')
        assert re.fullmatch(r'.+-[0-9]+:.+\.(x86_64|aarch64|noarch)', p['nevra'])
        assert p['nevra'].endswith(('.noarch', '.x86_64' if arch == 'amd64' else '.aarch64'))
for path in Path('.github/workflows').glob('*.yml'):
    text = path.read_text()
    workflow = yaml.safe_load(text)
    assert workflow['permissions'] == {'contents': 'read'}, path
    assert 'tags:' not in text and 'pull_request_target' not in text, path
    assert 'conformance.yml' not in text and 'release-eligible' not in text, path
    for use in re.findall(r'uses:\s*(\S+)', text):
        assert re.fullmatch(r'[^@]+@[0-9a-f]{40}', use), use
    assert 'persist-credentials: false' in text, path
for path in Path('scripts').glob('*.sh'):
    subprocess.run(['bash', '-n', str(path)], check=True)
print('Lock and workflow invariants: PASS')

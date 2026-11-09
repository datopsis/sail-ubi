#!/usr/bin/env python3
"""Propose exact CI scanner archives and independently record their bytes."""
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

lock = {}
for name, repo in [('trivy', 'aquasecurity/trivy'), ('grype', 'anchore/grype'), ('syft', 'anchore/syft')]:
    release = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/releases/latest']))
    version = release['tag_name'].removeprefix('v')
    lock[name] = {'version': version, 'architectures': {}}
    for arch in ['amd64', 'arm64']:
        suffix = {'amd64': 'Linux-64bit', 'arm64': 'Linux-ARM64'}[arch] if name == 'trivy' else 'linux_' + arch
        filename = f'{name}_{version}_{suffix}.tar.gz'
        asset = next(a for a in release['assets'] if a['name'] == filename)
        url = asset['browser_download_url']
        with urllib.request.urlopen(url) as response:
            data = response.read()
        digest = hashlib.sha256(data).hexdigest()
        if asset.get('digest') and asset['digest'] != 'sha256:' + digest:
            raise ValueError('GitHub asset digest mismatch')
        lock[name]['architectures'][arch] = {'url': url, 'sha256': digest}
        print(name, version, arch, flush=True)
Path('.github/tools.lock.json').write_text(json.dumps(lock, indent=2) + '\n')

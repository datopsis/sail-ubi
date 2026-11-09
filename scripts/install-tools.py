#!/usr/bin/env python3
"""Install checksum-pinned scanner binaries in .tools without executing an installer."""
import hashlib
import io
import json
import platform
import tarfile
import urllib.request
from pathlib import Path

arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}[platform.machine()]
Path('.tools').mkdir(exist_ok=True)
for name, tool in json.loads(Path('.github/tools.lock.json').read_text()).items():
    entry = tool['architectures'][arch]
    with urllib.request.urlopen(entry['url'], timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise ValueError('tool hash mismatch: ' + name)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        member = archive.getmember(name)
        if not member.isfile():
            raise ValueError('tool is not a regular file')
        path = Path('.tools') / name
        path.write_bytes(archive.extractfile(member).read())
        path.chmod(0o755)

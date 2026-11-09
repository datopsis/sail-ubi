#!/usr/bin/env python3
"""Resolve a complete UBI runtime closure. Update tool only; never used by builds."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path

import dnf
import dnf.repo

REQUESTED = ['python3.12', 'coreutils-single', 'ca-certificates', 'tzdata', 'libgcc', 'libstdc++']


def resolve(arch):
    rpm_arch = {'amd64': 'x86_64', 'arm64': 'aarch64'}[arch]
    with tempfile.TemporaryDirectory() as tmp, dnf.Base() as base:
        for name in ['root', 'cache', 'persist']:
            Path(tmp, name).mkdir()
        base.conf.installroot = tmp + '/root'
        base.conf.cachedir = tmp + '/cache'
        base.conf.logdir = tmp
        base.conf.persistdir = tmp + '/persist'
        base.conf.install_weak_deps = False
        base.conf.arch = rpm_arch
        base.conf.ignorearch = True
        base.conf.substitutions.update(arch=rpm_arch, basearch=rpm_arch, releasever='9')
        base.conf.module_platform_id = 'platform:el9'
        for name in ['baseos', 'appstream']:
            repo = dnf.repo.Repo(name, base.conf)
            repo.baseurl = [f'https://cdn-ubi.redhat.com/content/public/ubi/dist/ubi9/9/{rpm_arch}/{name}/os/']
            repo.gpgcheck = True
            base.repos.add(repo)
        base.fill_sack(load_system_repo=False)
        for name in REQUESTED:
            base.install(name)
        base.resolve()
        packages = sorted(base.transaction.install_set, key=str)
        base.download_packages(packages)
        result = []
        for p in packages:
            path = Path(p.localPkg())
            result.append(dict(nevra=f'{p.name}-{p.epoch}:{p.version}-{p.release}.{p.arch}',
                               filename=path.name, url=p.remote_location(),
                               sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                               size=path.stat().st_size, source_rpm=p.sourcerpm))
        return sorted(result, key=lambda x: x['nevra'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/rpms.lock.json')
    args = parser.parse_args()
    lock = {'requested': REQUESTED, 'architectures': {}}
    for arch in ['amd64', 'arm64']:
        lock['architectures'][arch] = resolve(arch)
        print(arch, len(lock['architectures'][arch]), 'RPMs', flush=True)
    Path(args.output).write_text(json.dumps(lock, indent=2) + '\n')

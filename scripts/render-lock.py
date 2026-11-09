#!/usr/bin/env python3
"""Render offline build verification manifests from the reviewed JSON locks."""
import argparse

from locklib import ROOT, inputs, read_lock


def render(check=False):
    lock = read_lock('sail.lock.json')
    outputs = {}
    for arch in ['amd64', 'arm64']:
        outputs[f'artifacts/{arch}.sha256'] = ''.join(f"{p['sha256']}  {name}\n" for name, p in sorted(inputs(arch).items()))
        outputs[f'artifacts/{arch}.nevra'] = ''.join(f"{p['filename']}\t{p['nevra']}\t{p['source_rpm']}\n"
                                                     for p in read_lock('rpms.lock.json')['architectures'][arch])
    for name, content in outputs.items():
        path = ROOT / name
        if check:
            assert path.read_text() == content, f'stale generated file: {name}'
        else:
            path.write_text(content)
    path = ROOT / 'Containerfile'
    text = path.read_text()
    import re
    for role, arg in [('builder', 'UBI_MINIMAL_IMAGE'), ('runtime', 'UBI_MICRO_IMAGE')]:
        expected = f'ARG {arg}="{lock["base_images"][role]}"'
        if check:
            assert expected in text, f'base pin mismatch: {role}'
        else:
            text = re.sub(rf'^ARG {arg}=.*$', expected, text, flags=re.MULTILINE)
    if not check:
        path.write_text(text)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    render(parser.parse_args().check)

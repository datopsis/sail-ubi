"""Lock helpers shared by acquisition, rendering and tests."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_lock(name):
    return json.loads((ROOT / 'artifacts' / name).read_text())


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inputs(arch):
    lock = read_lock('sail.lock.json')
    result = {}
    for p in read_lock('rpms.lock.json')['architectures'][arch]:
        result['rpms/' + p['filename']] = p
    for p in lock['rpm_keys']:
        result['keys/' + p['filename']] = p
    selected = lock['architectures'][arch]
    result['wheel/' + selected['wheel']['filename']] = selected['wheel']
    result['provenance.json'] = selected['provenance']
    for name, p in lock['source'].items():
        result['source/' + name] = p
    return result


def verify(path, entry):
    if path.is_symlink() or path.stat().st_size != entry['size'] or digest(path) != entry['sha256']:
        raise ValueError(f'locked digest/size mismatch: {path}')


def verify_bundle(directory, arch):
    expected = inputs(arch)
    actual = {str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != expected.keys():
        raise ValueError(f'bundle input set mismatch: {actual ^ expected.keys()}')
    for name, entry in expected.items():
        verify(directory / name, entry)

"""Runs inside the restricted container; examines actual process state."""
import importlib.metadata
import json
import os
import shutil
import socket
import sys
from pathlib import Path

assert os.getuid() != 0
for status in Path('/proc').glob('[0-9]*/status'):
    fields = dict(line.split(':', 1) for line in status.read_text().splitlines() if ':' in line)
    assert all(int(uid) != 0 for uid in fields['Uid'].split()), fields
    for field in ['CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb']:
        assert int(fields[field].strip(), 16) == 0, fields
    assert fields['NoNewPrivs'].strip() == '1', fields
assert os.statvfs('/').f_flag & os.ST_RDONLY
for path in ['/etc/forbidden', '/opt/sail/forbidden']:
    try:
        Path(path).touch()
    except OSError as error:
        assert error.errno in (13, 30), error  # EROFS, not merely UID permission denial
    else:
        raise AssertionError('root filesystem is writable')
for tool in ['rpm', 'dnf', 'microdnf', 'yum', 'pip', 'pip3', 'pip3.12']:
    assert shutil.which(tool) is None, tool
assert not list(Path('/usr').rglob('pip-*.whl'))
assert not list(Path('/usr').rglob('ensurepip/__init__.py'))
assert not list(Path('/usr').rglob('pip/__init__.py'))
sys.path.insert(0, '/opt/sail/python')
from pysail import _native
version = json.loads(Path('/opt/sail/artifact-lock.json').read_text())['version']
assert importlib.metadata.version('pysail') == version
assert _native._SAIL_VERSION == version
config = json.loads(Path(os.environ.get('SAIL_UBI_CONFIG', '/etc/sail/config.json')).read_text())
with socket.create_connection(('127.0.0.1', config['port']), timeout=5):
    pass
listeners = []
for table in ['tcp', 'tcp6']:
    for line in Path('/proc/net/' + table).read_text().splitlines()[1:]:
        fields = line.split()
        if fields[3] != '0A':
            continue
        addr, port = fields[1].split(':')
        if addr == '0B00007F':  # Docker's internal DNS listener
            continue
        listeners.append((addr, int(port, 16)))
assert listeners == [('0100007F' if config['bind'] == '127.0.0.1' else '00000000', config['port'])], listeners
print(json.dumps({'version': version, 'uid': os.getuid(), 'listeners': listeners,
                  'readonly_root': True, 'capabilities': 0, 'no_new_privileges': True}))

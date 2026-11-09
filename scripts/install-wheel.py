"""Install the already verified, dependency-free wheel without pip."""
import zipfile
from pathlib import Path

root = Path('/opt/sail/python')
with zipfile.ZipFile('/tmp/sail.whl') as archive:
    for item in archive.infolist():
        name = Path(item.filename)
        if name.is_absolute() or '..' in name.parts or (item.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError('unsafe wheel member')
    archive.extractall(root)
for path in root.rglob('*'):
    path.chmod(0o755 if path.is_dir() else 0o644)

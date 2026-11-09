#!/usr/bin/env python3
"""Reject reports that omitted the OS, Sail wheel or declared Rust dependencies."""
import json
from pathlib import Path

lock = json.loads(Path('artifacts/sail.lock.json').read_text())
sbom = json.loads(Path('evidence/image.spdx.json').read_text())
packages = sbom['packages']
assert any(p['name'] == 'pysail' and p['versionInfo'] == lock['version'] for p in packages), 'Sail wheel missing from SBOM'
assert any(p['name'] == 'python3.12' for p in packages), 'RPM inventory missing from SBOM'
assert sum('pkg:cargo/' in str(p.get('externalRefs')) for p in packages) > 100, 'declared Rust inventory missing'
report = json.loads(Path('evidence/trivy.json').read_text())
results = report['Results']
assert any(r.get('Type') == 'redhat' for r in results), 'Trivy OS coverage missing'
assert any(r.get('Type') == 'python-pkg' for r in results), 'Trivy wheel coverage missing'
assert any(r.get('Type') == 'cargo' for r in results), 'Trivy declared Rust coverage missing'
print('Scanner coverage: RPMs, pysail wheel and declared Rust graph present')

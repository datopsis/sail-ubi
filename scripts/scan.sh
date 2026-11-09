#!/usr/bin/env bash
# Produce complete reports first; evaluate both gates even if one fails.
set -Eeuo pipefail
mkdir -p evidence
image="${IMAGE:-localhost/sail-ubi:test}"
.tools/syft "$image" --select-catalogers +rust-cargo-lock-cataloger -o spdx-json=evidence/image.spdx.json
.tools/trivy image --scanners vuln --format json --output evidence/trivy.json "$image"
.tools/grype "sbom:evidence/image.spdx.json" -o json > evidence/grype.json
python scripts/vulnerability-gate.py evidence/trivy.json evidence/grype.json

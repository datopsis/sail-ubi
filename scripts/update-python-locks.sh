#!/usr/bin/env bash
set -Eeuo pipefail
for name in ci client; do
    pip-compile --generate-hashes --allow-unsafe --no-emit-index-url --no-emit-trusted-host \
        --no-reuse-hashes --output-file=".github/requirements/${name}.txt" \
        ".github/requirements/${name}.in"
done

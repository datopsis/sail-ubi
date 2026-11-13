#!/usr/bin/env bash
# Build the approved test-only proxy through its own verified/offline path.
set -euo pipefail
revision=9ef9e822c6b5e508cebef2adff3bb647a206773c
source_dir=${NGINX_SOURCE:?set NGINX_SOURCE outside the Sail checkout}
architecture=${ARCHITECTURE:?set native ARCHITECTURE}
git clone --quiet https://github.com/datopsis/nginx-ubi.git "$source_dir"
git -C "$source_dir" checkout --quiet "$revision"
test "$(git -C "$source_dir" rev-parse HEAD)" = "$revision"
cd "$source_dir"
python scripts/artifacts.py acquire --lock "artifacts/locks/${architecture}.json" \
    --output ".artifact-bundle/${architecture}"
CONTAINER_RUNTIME=podman bash scripts/build-image.sh "$architecture" localhost/sail-tls-proxy:test
podman save --format docker-archive localhost/sail-tls-proxy:test | docker load

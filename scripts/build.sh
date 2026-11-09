#!/usr/bin/env bash
set -Eeuo pipefail
runtime="${CONTAINER_RUNTIME:-podman}"
arch="${ARCHITECTURE:-$(uname -m)}"
case "$arch" in x86_64) arch=amd64;; aarch64) arch=arm64;; amd64|arm64) ;; *) exit 1;; esac
python scripts/render-lock.py --check
python scripts/fetch.py --arch "$arch"
lock_hash="$(cat artifacts/sail.lock.json artifacts/rpms.lock.json | sha256sum | cut -d' ' -f1)"
if test "$runtime" = docker; then
    build=(docker buildx build --load)
else
    build=("$runtime" build --format docker)
fi
"${build[@]}" --network=none --file Containerfile \
    --platform "linux/${arch}" \
    --build-context "artifact_bundle=.artifact-bundle/${arch}" \
    --build-arg "TARGETARCH=$arch" --build-arg "ARTIFACT_LOCK_SHA256=$lock_hash" \
    --build-arg "REVISION=$(git rev-parse HEAD)" \
    --build-arg "CREATED=$(git show -s --format=%cI HEAD)" \
    --tag "${IMAGE:-localhost/sail-ubi:test}" .

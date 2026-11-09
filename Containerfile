ARG UBI_MINIMAL_IMAGE="registry.access.redhat.com/ubi9/ubi-minimal:9.8@sha256:f26ef64172ea61f5ac5ba4be8c5c738bf8760b22b3e5148ce7b40f7308ab32db"
ARG UBI_MICRO_IMAGE="registry.access.redhat.com/ubi9/ubi-micro:9.8@sha256:d3499a0896e2d6a1642f922615831bc5c2fd513bbb34f3446cabba530d9d54a2"

FROM scratch AS artifact_bundle
FROM ${UBI_MICRO_IMAGE} AS microbase
FROM ${UBI_MINIMAL_IMAGE} AS builder
ARG TARGETARCH
COPY --from=microbase / /runtime/
COPY --from=artifact_bundle / /bundle/
COPY artifacts/ /locks/
COPY scripts/install-bundle.sh /usr/local/bin/install-bundle
COPY scripts/install-wheel.py /runtime/tmp/install-wheel.py
RUN /bin/bash /usr/local/bin/install-bundle "${TARGETARCH}"

FROM ${UBI_MICRO_IMAGE}
ARG ARTIFACT_LOCK_SHA256
ARG REVISION="unknown"
ARG CREATED="1970-01-01T00:00:00Z"
ARG UBI_MICRO_IMAGE
LABEL org.opencontainers.image.title="Sail on Red Hat UBI 9" \
      org.opencontainers.image.description="Rootless local Spark Connect server" \
      org.opencontainers.image.source="https://github.com/datopsis/sail-ubi" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="0.7.3" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.base.name="${UBI_MICRO_IMAGE}" \
      io.datopsis.artifact-lock.sha256="${ARTIFACT_LOCK_SHA256}"
COPY --from=builder /runtime/ /
COPY --chown=0:0 --chmod=0444 container/entrypoint.py container/healthcheck.py /opt/sail/
COPY --chown=0:0 --chmod=0444 container/config.json /etc/sail/config.json
ENV LANG="C.UTF-8" HOME="/var/lib/sail" TMPDIR="/tmp" PYTHONDONTWRITEBYTECODE="1"
USER 10001:10001
WORKDIR /var/lib/sail
EXPOSE 50051
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["/usr/bin/python3.12", "-I", "-B", "/opt/sail/healthcheck.py"]
STOPSIGNAL SIGINT
ENTRYPOINT ["/usr/bin/python3.12", "-I", "-B", "/opt/sail/entrypoint.py"]
CMD ["spark-connect"]

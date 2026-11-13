# Sail on UBI 9

Security-oriented, rootless [LakeSail Sail](https://github.com/lakehq/sail)
0.7.3 on digest-pinned Red Hat UBI 9.8 Micro. This is the first development
increment, **not a published or production-qualified release**.

The supported role is a single-process, local-mode Spark Connect server.
SQL/DataFrame execution and local Parquet I/O are tested using a real
`pyspark-client==4.2.0` client on native Linux amd64 and arm64 runners. This is
not a claim of full Spark compatibility or Kubernetes/OpenShift qualification.
Workers, cluster modes, Flight SQL, MCP and arbitrary command passthrough are
rejected by the entrypoint.

**Spark Connect has no built-in authentication to rely on.** The default bind
is `127.0.0.1:50051` inside the container's network namespace. Publishing a
container port does not make that loopback listener externally reachable.
A deployment must provide a TLS gateway and isolate the backend from untrusted
clients. [Phase A TLS qualification](docs/TLS.md) covers the owner-approved
shared-namespace NGINX design: TLS on 50051, Sail loopback on 50052, and a narrow
plaintext loopback exception. Phase A provides server identity and encryption;
client authentication is Phase B. SQL can access files and external data sources with the
server's permissions; treat access to this endpoint as access to its identity.

**Known limitation — slow consumers of large results through the TLS proxy:**
Sail 0.7.3 can reset the stream near 80 seconds with gRPC INTERNAL/RST_STREAM 2.
Use the [copy-paste PySpark retry/reattach policy](docs/TLS.md#recommended-client-policy)
for the pinned client. It recovers the tested read result after the reset; it
does not prevent the transport failure. Repeated drops, server restart,
retention expiry and mutating SQL are **untested**.

Owner decision (2026-11-13): document + retry + upstream. Native CI requires an
[exact-outcome canary and blocking recovery check](docs/TLS.md#owner-approved-stream-checks).
Unexpected default-client success emits a notice and fails for review; a different
error also fails. Recovery must prove all million IDs exactly once, hashes, sum
and ExecutePlan → ReattachExecute. Custom-root REST/S3 support, certificate
negatives and hardening checks remain mandatory. The
[upstream keepalive feature request](docs/known-issues/sail-keepalive.md) is drafted
here only; it has not been filed. Engine and proxy pins remain unchanged.

## Build and verify

Host tools: Python 3.11 with a virtual environment, Podman or Docker with
Buildx, RPM/rpmkeys, GnuPG and Git. `gh` is needed for lock updates and issue
tracking. System Python DNF/RPM bindings are needed for lock updates and
repository-aware vulnerability admission. Install the existing locked requirements:

```sh
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes --only-binary=:all: -r .github/requirements/ci.txt
python -m pip install --require-hashes --no-build-isolation -r .github/requirements/client.txt
pre-commit run --all-files
CONTAINER_RUNTIME=docker bash scripts/build.sh
CONTAINER_RUNTIME=docker python tests/runtime.py
python scripts/install-tools.py
ARCHITECTURE=amd64 bash scripts/scan.sh # use arm64 on an arm64 host
```

The build script acquires the verified bundle, checks the generated manifests,
and disables networking during assembly. The Containerfile rechecks all input
hashes, RPM metadata and signatures. Bare builds without the bundle fail closed.
No dependency resolution or network package installation takes place in assembly.
Podman is exposed by the scripts but needs separate qualification; current native
CI uses Docker. Sandbox namespace restrictions may prevent local builds.

The final image has UID/GID `10001:10001`, no package manager, and no setuid or
setgid files added by this project. Python's pip bootstrap wheel and ensurepip
are removed. A Python interpreter and the UBI shell remain; this is not a
shell-free image or a security boundary against an operator overriding ENTRYPOINT.

## Run with the default loopback listener

```sh
docker run --rm --name sail --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges --pids-limit=256 --memory=2g --cpus=2 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=256m,mode=0700,uid=10001,gid=10001 \
  --tmpfs /var/lib/sail:rw,noexec,nosuid,nodev,size=256m,mode=0700,uid=10001,gid=10001 \
  localhost/sail-ubi:test
```

The two writable paths are `/tmp` (spill/temp files) and `/var/lib/sail` (working
directory, HOME, local data). These example mounts are ephemeral. For durable
local data supply a volume owned by UID/GID 10001 at `/var/lib/sail`, sized and
backed up by the operator. No other writable root paths are required. The system timezone is explicitly selected as `Etc/UTC`; merely installing
`tzdata` is insufficient for Sail session creation. Logs go to stdout/stderr. Configuration defaults to `/etc/sail/config.json`; override
its path with `SAIL_UBI_CONFIG` and mount the file read-only. Missing, malformed,
unknown/duplicate fields, invalid ports and unsupported upstream `SAIL_*`
overrides are startup errors, with useful diagnostics.

The exact `SAIL_CATALOG__LIST` environment variable is permitted for upstream
catalog configuration. AWS credential and object-store environment variables
pass through. See [Iceberg readiness and exact configuration](docs/ICEBERG.md):
0.7.3 supports Iceberg REST, but **cannot disable its vended-credentials request
header**. This is distinct from static S3 signing, which the TLS fixture proves
without changing credential mode. Neither the startup test nor the TLS fixtures
qualify Lakekeeper/SeaweedFS interoperability or a profile requiring header omission.

To place an authenticated gateway in a separate network namespace, supply
these exact configuration fields in a read-only file:

```json
{
  "bind": "0.0.0.0",
  "port": 50051,
  "allow_unauthenticated_remote": true
}
```

`allow_unauthenticated_remote` is an explicit opt-out of the loopback guard;
it does **not** enable authentication or encryption. Startup warns every time.
Do not expose the backend port publicly. Permit only the gateway to reach it,
terminate authenticated TLS there, and enforce client authorization outside Sail.
This separate-namespace opt-out is **not the Phase A design**; use the loopback
configuration and shared namespace in [TLS.md](docs/TLS.md). CI uses the
opt-out solely with a port published on the runner's `127.0.0.1`.

The healthcheck tests TCP liveness, not SQL execution or authentication. Sail is
PID 1 and `STOPSIGNAL SIGINT` matches upstream's graceful shutdown handler; CI
requires a clean stop within 20 seconds. The host/orchestrator must enforce
resource limits and the security options above; an image cannot impose them.

## Supply chain and evidence

[Artifact acquisition](docs/ARTIFACTS.md) records route selection, publisher
verification and limitations. The upstream wheel has no mandatory Python
dependencies. Native code is already compiled by upstream. Red Hat Python 3.12
and its RPM closure are locked per architecture; neither a JVM nor PySpark is
installed in the runtime.

CI runs lint/unit tests, native builds, restricted runtime tests, the Phase A TLS
qualification matrix (see its recorded status in [TLS.md](docs/TLS.md)), an SPDX SBOM,
and blocking Trivy/Grype gates on each architecture. Fixed RPM findings can be
deferred only when the vendor fix is absent from the configured UBI repositories;
see [the admission rule and tracking schedule](SECURITY.md). Full reports retain
deferred and unfixed findings. Source Cargo.lock is a conservative **declared dependency inventory**,
not proof of the crates compiled into the wheel. See [roadmap](docs/ROADMAP.md)
for remaining evidence. CI artifacts are retained for 14 days.

`update-locks.yml` is read-only: it proposes refreshed files and a patch for
owner review. It never commits, opens a PR, signs or publishes. No tag triggers
publishing. Repository protections and required checks are owner responsibilities;
this PR changes no GitHub settings.

## Layout

- `Containerfile`, `container/`: runtime assembly, role/configuration guard and probe.
- `artifacts/`: Sail/base/signing-key and per-architecture RPM locks; offline manifests.
- `scripts/`: acquisition/verification, lock regeneration, build, lint and scans.
- `tests/`: negative security cases, bundle tampering and real Spark Connect requests.
- `.github/`: read-only CI/update workflows, scanner locks and complete Python tool locks.
- `docs/`: acquisition decisions, ordered roadmap and version rules.

Repository and Sail code are Apache-2.0. UBI/RPMs and bundled dependencies retain
their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

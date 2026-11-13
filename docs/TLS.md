# Phase A: Sail TLS qualification

Sail remains **0.7.3**. It has no native TLS listener. The owner-approved design
uses [datopsis/nginx-ubi at 9ef9e822c6b5e508cebef2adff3bb647a206773c](https://github.com/datopsis/nginx-ubi/tree/9ef9e822c6b5e508cebef2adff3bb647a206773c),
with its unchanged `examples/profiles/sail/nginx.conf`. NGINX serves TLS HTTP/2
on 50051 and forwards gRPC to `127.0.0.1:50052` in the same network namespace.
This is dispatch item 6 of the
[TLS plan](https://github.com/datopsis/lakehouse-integration/blob/main/docs/TLS-PLAN.md).

**Qualification status: blocked by the paced Spark result stream.** Native
[CI run 43374005262](https://github.com/datopsis/sail-ubi/actions/runs/43374005262)
tested the harness at commit `3cb9d0c` with RSA-3072 per-run PKI on native
[amd64](https://github.com/datopsis/sail-ubi/actions/runs/43374005262/job/131716300580)
and [arm64](https://github.com/datopsis/sail-ubi/actions/runs/43374005262/job/131716300540).
Both produced 33 passing coverage entries and one failing stream entry. The
required stream assertion stays blocking; there is no exemption or shorter
replacement workload. This design is **not admitted as qualified Phase A**.

| Assertion | amd64 | arm64 |
| --- | --- | --- |
| Verified TLS Connect: SQL = 42 and aggregate = 2450 | PASS | PASS |
| Paced, complete 1,000,000-row result through proxy | **FAIL** | **FAIL** |
| Connect rejects wrong client CA | PASS | PASS |
| Connect rejects unrelated server issuer | PASS | PASS |
| Connect rejects correct CN / wrong SAN | PASS | PASS |
| Connect rejects expired certificate | PASS | PASS |
| Plaintext Connect rejected; IPv6 HTTP rejected | PASS | PASS |
| Sail loopback only; peer backend refusal; secret isolation | PASS | PASS |
| REST HTTPS with `SSL_CERT_FILE`: exact namespace row | PASS | PASS |
| S3 HTTPS with `SSL_CERT_FILE`: exact rows and static SigV4 | PASS | PASS |
| REST and S3 each reject missing CA | PASS | PASS |
| REST and S3 each reject wrong CA | PASS | PASS |
| REST and S3 each reject malformed CA | PASS | PASS |
| REST and S3 each reject unrelated server issuer | PASS | PASS |
| REST and S3 each reject correct CN / wrong SAN | PASS | PASS |
| REST and S3 each reject expired certificate | PASS | PASS |
| Valid recovery controls after every certificate mutation | PASS | PASS |
| Existing runtime/hardening, publisher, Trivy and Grype gates | PASS | PASS |

The proxied stream fails with gRPC `INTERNAL: Stream removed (RST_STREAM ...
error code 2)`. It returned only 155,648 rows / 19 batches on amd64 (80.24 seconds)
and 172,032 rows / 21 batches on arm64 (80.33 seconds). Proxy logs record about
15.33 MB and 16.63 MB respectively, so the failure is not the 10 MB wire-volume
threshold. The identical direct loopback control returns all 1,000,000 rows in
123 batches with exact sum 499999500000 and every SHA-512 payload verified:
81.88 seconds on amd64, 81.99 seconds on arm64. This diagnostic never publishes
the backend port and cannot substitute for the failing TLS assertion.

The pinned [Sail server builder](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/server/builder.rs)
sets a 60-second HTTP/2 keepalive interval and a 10-second acknowledgement timeout.
Interaction with proxy backpressure is a hypothesis, not an established root
cause. Resolving this requires a reviewed proxy/upstream investigation; this PR
does not alter the approved proxy profile, engine, retries to hide the error, or
security checks. **CA injection is supported on both paths and is not the blocker.**

## Deployment contract

Mount this Sail configuration read-only at `/etc/sail/config.json`:

```json
{
  "bind": "127.0.0.1",
  "port": 50052,
  "allow_unauthenticated_remote": false
}
```

The Sail container owns the network namespace. Start its proxy with Docker
`--network container:<sail-container>` or Compose `network_mode: service:sail`.
Publish only proxy port 50051 from the network-owning Sail container. Do not
publish 50052. Use the pinned NGINX profile with
`-c /etc/nginx/profile/nginx.conf -g 'daemon off;'`. Mount the profile read-only,
and mount only that proxy's leaf certificate and private key at
`/etc/nginx/tls/server.crt` and `/etc/nginx/tls/server.key`. Its SAN must match the
client's DNS target. The qualification fixture uses `localhost` for the runner;
a deployment using `sail` must issue a certificate for `sail`.

Preserve Sail's UID/GID 10001, read-only root, dropped capabilities,
no-new-privileges, resource limits, `/tmp` and `/var/lib/sail` writable mounts.
Run NGINX non-root with read-only root, dropped capabilities, no-new-privileges,
resource limits and only its declared `/tmp` writable mount. The containers share
networking, never PID namespaces, filesystems, or secret mounts. Sail gets public
trust material and its own static AWS credentials, never the proxy key. The proxy
gets no AWS credentials. The CA signing key stays outside both containers.
Per-run PKI uses RSA 3072/SHA-256, a 24-hour root with certificate-signing usage,
six-hour server leaves and five-minute clock skew allowance. The proxy's private
key is root-owned, group 0, mode 0440; the proxy runs as 10001:0. Public trust and
per-service leaf mounts remain separate. No CA signing key is written to disk.

**Narrow plaintext exception:** only NGINX → Sail on loopback 127.0.0.1:50052.
No plaintext bridge hop is permitted. This is proxy-terminated TLS, not native
Sail TLS or encryption on every hop. CI inventories IPv4/IPv6 sockets and probes
the backend from a separate container. Recreate the pair together so a proxy
cannot remain attached to an obsolete namespace.

Phase A supplies encryption and server identity only. Spark Connect remains
unauthenticated; client authentication is Phase B. Keep access restricted to
trusted clients: SQL can use Sail's filesystem and external-data identity.

## Client and qualified outbound trust

The client lock pins `pyspark-client==4.2.0`. Start a **fresh client process**
with `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/path/to/public-ca.pem`, then connect to
`sc://sail:50051/;use_ssl=true`. That gRPC environment variable must be set before
gRPC initialization. A `sc://` URL alone does not enable TLS. No hostname override,
verification bypass, client key or token is used in this Phase A test.

Both native architectures prove the outbound CA path: mount a public PEM bundle
read-only into Sail and set `SSL_CERT_FILE` before process startup. For example:

```sh
export SSL_CERT_FILE='/run/trust/ca.crt'
export SAIL_CATALOG__LIST='[{type="iceberg-rest", name="qualification", uri="https://catalog:8181/catalog", warehouse="qualification"}]'
export AWS_ENDPOINT='https://s3:8333'
export AWS_REGION='us-east-1'
export AWS_ALLOW_HTTP='false'
export AWS_VIRTUAL_HOSTED_STYLE_REQUEST='false'
```

Inject per-service static AWS credentials as already described in
[ICEBERG.md](ICEBERG.md). Do not use `AWS_CA_BUNDLE` as an assumed replacement
for the Rust clients' trust configuration. No system-trust replacement or binary
modification was needed. Both paths reject missing, wrong and malformed custom
roots. This is not a CA-injection support blocker. Restart clients after changing trust; live CA rotation,
revocation and exclusive trust-root pinning are not qualified.

## Exact test boundary

`tests/tls.py` runs after the unchanged native runtime tests and builds the
approved proxy through its own verified RPM/offline assembly scripts. Every
negative has a fresh client and valid controls before/after. Outbound cases
also restart Sail to avoid cached clients or sessions.

| Edge | Positive assertion | Negative assertions |
| --- | --- | --- |
| PySpark → NGINX → Sail | SQL = 42; aggregate = 2450; a paced Arrow result with 1,000,000 rows, exact ID sum 499999500000, each payload = SHA-512 of its decimal ID, at least 16 batches and 75 seconds | Wrong client CA, unrelated issuer, correct CN/wrong SAN, expired leaf, plaintext Connect |
| Sail → Iceberg REST HTTPS fixture | Actual `SHOW NAMESPACES`, exactly `tls_namespace` | Missing/wrong/malformed CA, unrelated issuer, correct CN/wrong SAN, expired leaf |
| Sail → S3 HTTPS fixture | Exact three Parquet rows over signed HEAD/GET; fixture validates SigV4 against per-run static credentials and rejects session tokens | Missing/wrong/malformed CA, unrelated issuer, correct CN/wrong SAN, expired leaf |
| Namespace boundary | Only Sail loopback 50052 and NGINX TLS 50051 on IPv4/IPv6; peer reaches proxy | Backend and auxiliary ports refuse peer connections; no IPv6 backend listener; no shared key/credential mounts |

Outbound rejection requires a certificate-specific TLS alert at the endpoint,
zero HTTP requests, and a failed real Sail operation. This retains evidence even
when the REST error wrapper hides reqwest's certificate cause. Timeout, HTTP 403,
or process startup failure is not an accepted certificate oracle.

These bounded protocol fixtures isolate transport behavior. They do not qualify
Lakekeeper/SeaweedFS interoperability, Iceberg mutations, STS, credential vending,
cross-engine reads, recovery, production PKI, Kubernetes or OpenShift. The paced
stream tests a long-lived result with client backpressure, including at least
75 seconds and 10 MB on a successful TLS HTTP/2 RPC in the proxy log, not Structured Streaming
or an hour-long idle RPC. The existing 0.7.3 delegation request behavior is unchanged.

Run with the existing hash-pinned CI/client dependencies and native container
tools:

```sh
export ARCHITECTURE=amd64 # arm64 on a native arm64 host
export NGINX_SOURCE="$(mktemp -d)/nginx"
bash scripts/build-tls-proxy.sh
CONTAINER_RUNTIME=docker python tests/tls.py
```

CI retains `evidence/tls/coverage.json`, public certificate metadata, sanitized
client/server logs and protocol events for 14 days. Temporary keys and credentials
are never committed or uploaded. The full Sail hardening/provenance and
Trivy/Grype gates remain blocking.

# Phase A: Sail TLS qualification

Sail remains **0.7.3**. It has no native TLS listener. The owner-approved design
uses [datopsis/nginx-ubi at 9ef9e822c6b5e508cebef2adff3bb647a206773c](https://github.com/datopsis/nginx-ubi/tree/9ef9e822c6b5e508cebef2adff3bb647a206773c),
with its unchanged `examples/profiles/sail/nginx.conf`. NGINX serves TLS HTTP/2
on 50051 and forwards gRPC to `127.0.0.1:50052` in the same network namespace.
This is dispatch item 6 of the
[TLS plan](https://github.com/datopsis/lakehouse-integration/blob/main/docs/TLS-PLAN.md).

**Known limitation: slow consumers of large results through the proxy can receive
gRPC INTERNAL (13), RST_STREAM error code 2, near 80 seconds.** The transport
failure remains present in Sail 0.7.3. On 2026-11-13 the owner chose **document +
retry + upstream**: track the default-client failure precisely and require
complete recovery with the recommended pinned-client policy. This is bounded
Phase A transport qualification with a documented limitation, not production or
platform certification. Client authentication remains Phase B.

The [diagnosis](evals/2026-11-13-sail-stream-reset.md) establishes that downstream
backpressure delays HTTP/2 PING progress; Sail initiates shutdown near 70 seconds
and the paced client sees it near 80 seconds. The
[fix-options evidence](evals/2026-11-13-sail-stream-fix-options.md) proves complete
cursor recovery on both native architectures. Sail exposes no keepalive override;
`grpc_buffer_size 64k;` and `1m;` both fail. The approved proxy profile and pinned
engine remain unchanged. The [upstream feature request](known-issues/sail-keepalive.md)
is a draft in this repository and has not been filed.

## Owner-approved stream checks

Both checks are mandatory in `tests/tls.py`, with fresh restricted containers,
verified TLS and the original million-row SHA-512 query, five-second pauses after
the first 16 batches. Missing evidence, timeout, process failure or a different
error fails CI. The 33 other TLS assertions remain unchanged.

| Blocking check | Exact required outcome |
| --- | --- |
| Default-policy canary | One reattachable ExecutePlan, no ReattachExecute; gRPC INTERNAL (numeric 13) and exactly `Stream removed (RST_STREAM (Received RST_STREAM with error code 2))`; SparkConnectGrpcException; partial rows, at least 16 batches; elapsed 70–90 seconds |
| Retry/reattach recovery | One failed ExecutePlan with that exact error, followed by one successful ReattachExecute; identical nonempty operation ID and nonempty resume cursor; all 1,000,000 IDs exactly once, every SHA-512 payload correct, sum 499999500000; at least 16 batches and 75 seconds |

If the default-policy stream starts completing, the canary emits a visible
GitHub Actions `notice` and **fails** for review. It cannot silently accept a fix,
an unrelated error or arbitrary nonzero exit. Successful canary classification
means the known limitation was reproduced; it does not mean that raw stream
succeeded. The recovery gate requires successful process exit and gRPC OK after
reattachment, never just an HTTP 200. Proxy logs independently require the exact
RPC sequence, TLS HTTP/2, and the original >=75-second / >10 MB ExecutePlan.

The native CI matrix runs on amd64 and arm64. Current head results are available
in [PR #5 checks](https://github.com/datopsis/sail-ubi/pull/5/checks); the historical
reports retain the measured evidence before this owner decision. Canary and
recovery records are separate entries in `evidence/tls/coverage.json`.

## Recommended client policy

Use `pyspark-client==4.2.0` and a fresh Python process. Set the public CA path
**before importing/initializing gRPC**:

```sh
export GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/path/to/public-ca.pem
```

Copy this policy (also [examples/spark_connect_retry.py](../examples/spark_connect_retry.py)).
CI imports this exact implementation; a regression test checks that this snippet
matches the tested file.

```python
"""Pinned PySpark 4.2.0 policy for Sail 0.7.3's documented proxy reset."""
import grpc
from pyspark.sql.connect.client.retries import RetryPolicy

RESET_DETAILS = 'Stream removed (RST_STREAM (Received RST_STREAM with error code 2))'


class ResetRetry(RetryPolicy):
    def __init__(self):
        # One retry per failed response-read context, with a one-second backoff.
        super().__init__(max_retries=1, initial_backoff=1000, max_backoff=1000)

    def can_retry(self, error):
        return (isinstance(error, grpc.RpcError)
                and error.code() == grpc.StatusCode.INTERNAL
                and error.details() == RESET_DETAILS)
```

Then create the verified-TLS session and install the policy before running queries:

```python
from pyspark.sql import SparkSession

spark = SparkSession.builder.remote("sc://sail:50051/;use_ssl=true").getOrCreate()
spark.client.enable_reattachable_execute()
spark.client.set_retry_policies([ResetRetry()])
try:
    print(spark.sql("SELECT 40 + 2 AS answer").collect())
finally:
    spark.stop()
```

The server certificate SAN must match `sail` (or the hostname you use). The policy
matches only the pinned client's exact INTERNAL/reset detail; certificate errors,
other INTERNAL errors, SQL errors and arbitrary exceptions do not match. It uses
PySpark's cursor reattachment, not a manual re-execution of SQL. The one-retry
limit applies per failed response-read context, not globally to an indefinitely
long query. The CI process also has a 240-second outer timeout.

**Untested limits:** repeated drops, server restart/session loss, retention expiry
or exhaustion, mutating SQL, indefinitely slow readers and other client versions.
The qualification covers one reset while reading this result; it does not grant
exactly-once guarantees for writes. The configured policy recovers after the
failure; it does not remove the server/proxy transport limitation. Phase A still
provides encryption and server identity only, with no client authentication.

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
| PySpark → NGINX → Sail | SQL = 42; aggregate = 2450; a paced Arrow result recovered via ReattachExecute with 1,000,000 unique IDs, exact ID sum 499999500000, each payload = SHA-512 of its decimal ID, at least 16 batches and 75 seconds | Wrong client CA, unrelated issuer, correct CN/wrong SAN, expired leaf, plaintext Connect |
| Sail → Iceberg REST HTTPS fixture | Actual `SHOW NAMESPACES`, exactly `tls_namespace` | Missing/wrong/malformed CA, unrelated issuer, correct CN/wrong SAN, expired leaf |
| Sail → S3 HTTPS fixture | Exact three Parquet rows over signed HEAD/GET; fixture validates SigV4 against per-run static credentials and rejects session tokens | Missing/wrong/malformed CA, unrelated issuer, correct CN/wrong SAN, expired leaf |
| Namespace boundary | Only Sail loopback 50052 and NGINX TLS 50051 on IPv4/IPv6; peer reaches proxy | Backend and auxiliary ports refuse peer connections; no IPv6 backend listener; no shared key/credential mounts |

Outbound rejection requires a certificate-specific TLS alert at the endpoint,
zero HTTP requests, and a failed real Sail operation. This retains evidence even
when the REST error wrapper hides reqwest's certificate cause. Timeout, HTTP 403,
or process startup failure is not an accepted certificate oracle.

These bounded protocol fixtures isolate transport behavior. They do not qualify
Lakekeeper/SeaweedFS interoperability, Iceberg mutations, STS, credential vending,
cross-engine reads, general failure recovery, production PKI, Kubernetes or OpenShift. The paced
stream tests a long-lived result with client backpressure, including at least
75 seconds and 10 MB on the initial TLS HTTP/2 RPC, followed by verified cursor recovery, not Structured Streaming
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

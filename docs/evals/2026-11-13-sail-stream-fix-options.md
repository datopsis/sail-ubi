# Sail 0.7.3 stream fix options — 2026-11-13

Historical evidence before the owner's final 2026-11-13 decision. The measured
results below remain unchanged. Current admission uses the
[document + retry + upstream contract](../TLS.md#owner-approved-stream-checks):
an exact default-policy failure canary plus blocking complete recovery. Earlier
references here to a draft/red raw-stream gate describe the evaluated commits.

PR #5 stays draft. The original slow-consumer qualification, thresholds, engine,
production proxy profile, credential mode and hardening remain unchanged.
These are separate diagnostic variants of the same million-row SHA-512 query,
with five-second sleeps after the first 16 Arrow batches. See the
[reset diagnosis](2026-11-13-sail-stream-reset.md) for the established cause.

## Result and recommendation

**The exact-reset PySpark policy is a demonstrated recovery option on both
architectures. It reattaches and returns the complete result after the reset;
it does not prevent the transport failure.** Neither tested NGINX buffer setting
fixes the failure, and Sail exposes no supported keepalive setting.

[Native CI run 43383736530](https://github.com/datopsis/sail-ubi/actions/runs/43383736530)
executes harness commit `32713fe` on
[amd64](https://github.com/datopsis/sail-ubi/actions/runs/43383736530/job/131747571962)
and [arm64](https://github.com/datopsis/sail-ubi/actions/runs/43383736530/job/131747572069).
Actual job logs and both evidence artifacts were read. Each candidate uses a
fresh restricted Sail/proxy pair, fresh verified TLS, the same pinned client and
original pacing/result size. All eight captures pass zero-drop/integrity checks.

| Separate variant | amd64 | arm64 |
| --- | --- | --- |
| Untouched PySpark default retry policy | FAIL: INTERNAL (13), 163,840 rows / 20 batches, 80.302 s | FAIL: INTERNAL (13), 163,840 rows / 20 batches, 80.342 s |
| Exact-reset custom policy | PASS: 1,000,000 unique rows / 123 batches, 83.021 s | PASS: 1,000,000 unique rows / 123 batches, 83.188 s |
| `grpc_buffer_size 64k;`, original retry policy | FAIL: INTERNAL (13), 155,648 rows / 19 batches, 80.268 s | FAIL: INTERNAL (13), 163,840 rows / 20 batches, 80.350 s |
| `grpc_buffer_size 1m;`, original retry policy | FAIL: INTERNAL (13), 188,416 rows / 23 batches, 80.306 s | FAIL: INTERNAL (13), 196,608 rows / 24 batches, 80.392 s |
| Supported Sail keepalive configuration variant | Not available in pinned source | Not available in pinned source |

The exact failure details in every negative row are the INTERNAL/RST_STREAM-2
message quoted below. The configured buffer sizes are confirmed by each retained
`nginx -T`. All four buffer variants still log Sail's local NO_ERROR shutdown at
about 70 seconds. Backend control frames remain late: amd64 64k PING/ACK occurs
at 80.215/80.225 s before TCP reset; arm64 1m PING/ACK at 80.259/80.297 s with
GOAWAY(0) and closure. The other two runs close with GOAWAY(0)/FIN without a
second PING reaching the wire. Neither directive keeps keepalive progress timely.

The successful policy sees ExecutePlan fail at 80.341/80.337 s, waits one second,
and starts ReattachExecute at 81.341/81.338 s. Both runs record **exactly one
ExecutePlan and one ReattachExecute**, identical nonempty operation IDs across
them, a nonempty last-response cursor, then gRPC OK on the reattachment. Proxy
access logs independently show the ReattachExecute RPC. There is no new
ExecutePlan. Final ID membership is exactly 0 through 999,999 with no duplicates
or gaps, sum 499999500000, and every SHA-512 payload verified.

Recommend the narrowly matched, bounded custom client policy **only as an
explicit recovery contract for the pinned client and this read-query workload**,
if the owner chooses application-level recovery. Do not describe it as a proxy
fix or turn on retries for every INTERNAL error. Do not route `64k` or `1m` as a
fix to nginx-ubi; both failed. A general transport fix still needs upstream
control-frame progress or keepalive accounting changes. No supported Sail
configuration-only route exists for 0.7.3.

The original qualification stays red: **33 PASS entries and one stream FAIL on
each architecture**. Runtime/hardening, publisher verification, Trivy and Grype
pass. The separate diagnostics retain outcomes, including expected errors; their
successful orchestration step does not grant Phase A admission. No default is
changed to accept the known failure, and no expected-failure waiver replaces
the original positive stream assertion. The owner decides whether to accept a
client recovery contract or require an upstream transport fix.

Not qualified: indefinitely slow readers, repeated disconnects, exhausted or
expired response retention, server restart/session loss, mutating SQL, other
clients/versions, or other buffer sizes. The original pacing becomes fast after
the first 16 batches, so this proves one real reset/recovery, not an indefinitely
backpressured subscription. The frontend TLS stream was not decrypted. Per-case
client/server logs, control frames, effective configs and result records remain
under `evidence/stream-fix-options/` for CI's 14-day artifact retention.

## Sail keepalive configuration

There is **no supported Sail 0.7.3 configuration key or environment variable**
that changes or disables Spark Connect's HTTP/2 keepalive. The pinned source
commit is `ac4690078021cf2a5402dc5c7b38a886f1916c73`.

- [ServerBuilderOptions defaults, lines 24–32](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/server/builder.rs#L24-L32):
  HTTP/2 interval = 60 seconds, timeout = 10 seconds, adaptive window enabled.
- [Applied to tonic, lines 64–69](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/server/builder.rs#L64-L69).
- [Spark Connect entrypoint, lines 49–67](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-spark-connect/src/entrypoint.rs#L49-L67):
  `AppConfig` goes into the session manager; `ServerBuilder::new` receives
  `Default::default()` directly. It never reads transport options from config.
- [Config loader, lines 74–82](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/config/application.rs#L74-L82):
  `SAIL_` names map `__` to nested configuration paths. The
  [Spark config struct, lines 949–954](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/config/application.rs#L949-L954)
  contains only session timeout and execution heartbeat interval. The
  [schema descriptions, lines 983–998](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/config/application.yaml#L983-L998)
  concern session lifetime/application heartbeat responses, not HTTP/2 PING.

The complete pinned source was searched for `keepalive`, `keep_alive`,
`http2_keepalive` and server-builder call sites, including the configuration
schema and documentation. The optional Rust builder fields are implementation
API, not exposed settings of the shipped binary. No invented environment key,
launcher exemption, timer change, binary patch or rebuild was tested. A
configured Sail variant is therefore **not applicable**, not a missing CI pass.

## NGINX upstream handling

The approved nginx-ubi commit remains
`9ef9e822c6b5e508cebef2adff3bb647a206773c`; its shipped NGINX is 1.30.6.
The source explains both PING acknowledgement and its limitation:

- [PING parsing and writer scheduling](https://github.com/nginx/nginx/blob/release-1.30.6/src/http/modules/ngx_http_grpc_module.c#L2384-L2397),
  [ACK creation after parsing](https://github.com/nginx/nginx/blob/release-1.30.6/src/http/modules/ngx_http_grpc_module.c#L4089-L4099).
- [Hardcoded nonbuffered forwarding](https://github.com/nginx/nginx/blob/release-1.30.6/src/http/modules/ngx_http_grpc_module.c#L4510-L4517).
  There is no `grpc_buffering` directive. `proxy_buffering` belongs to the HTTP
  proxy module and does not enable gRPC response spooling.
- [Buffer-size directive](https://github.com/nginx/nginx/blob/release-1.30.6/src/http/modules/ngx_http_grpc_module.c#L300-L305)
  and [default of one memory page](https://github.com/nginx/nginx/blob/release-1.30.6/src/http/modules/ngx_http_grpc_module.c#L4565-L4567).
- [Busy-buffer handling and conditional upstream read](https://github.com/nginx/nginx/blob/release-1.30.6/src/http/ngx_http_upstream.c#L3951-L4008).
  Enlarging a finite buffer does not provide a separate path for control frames
  behind DATA on the same TCP byte stream. The module advertises a
  [2,147,483,647-byte receive window](https://github.com/nginx/nginx/blob/release-1.30.6/src/http/modules/ngx_http_grpc_module.c#L4359-L4364).

The candidates insert exactly `grpc_buffer_size 64k;` or
`grpc_buffer_size 1m;` beside `grpc_pass` in a temporary diagnostic profile.
They use the original client policy, pacing, result size and 3600-second profile
timeouts. nginx-ubi is never modified. Effective `nginx -T`, info/access logs,
Sail logs and passive backend TCP/HTTP2 control frames are retained for each.

## PySpark recovery path

Pinned pyspark-client 4.2.0 installs its
[default retry policy](https://github.com/apache/spark/blob/v4.2.0/python/pyspark/sql/connect/client/core.py#L708-L712).
Its [error predicate](https://github.com/apache/spark/blob/v4.2.0/python/pyspark/sql/connect/client/retries.py#L337-L372)
does not retry this generic INTERNAL reset; the INTERNAL branch requires
`INVALID_CURSOR.DISCONNECTED`, while separate rules handle UNAVAILABLE and
server RetryInfo. Increasing the default retry count does not change that
predicate. The `client-default` control leaves the built-in policy untouched.

A [custom policy hook](https://github.com/apache/spark/blob/v4.2.0/python/pyspark/sql/connect/client/core.py#L818-L824)
can classify the exact status/detail as retryable. The `client-reset-retry`
experiment uses `RetryPolicy(max_retries=1, initial_backoff=1000,
max_backoff=1000)` and matches only gRPC INTERNAL plus:

```text
Stream removed (RST_STREAM (Received RST_STREAM with error code 2))
```

The retry bound is per PySpark retry context, not a global limit over an
arbitrarily long query. This experiment's client process is bounded to 240 s.
It does not retry certificate errors, UNAVAILABLE, unrelated INTERNAL errors,
SQL errors or arbitrary exceptions. A local predicate/bound check covers these
nonmatches and exhaustion after one retry.

[PySpark's iterator](https://github.com/apache/spark/blob/v4.2.0/python/pyspark/sql/connect/client/reattach.py#L253-L315)
clears the failed transport iterator and, if the policy allows retry, sends
ReattachExecute with the original operation ID and last returned response ID.
Sail's [reattach handler](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-spark-connect/src/service/plan_executor.rs#L617-L640)
finds that executor, releases acknowledged responses and resumes its output.
A [send failure pauses the executor](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-spark-connect/src/executor.rs#L370-L380).
Its [retention buffer is 128 outputs](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-spark-connect/src/executor.rs#L70-L90),
not an unlimited recovery guarantee.

This is application-level cursor reattachment, not a new SQL execution or
ordinary gRPC retry. [gRPC commits an RPC after response headers](https://grpc.io/docs/guides/retry/#how-grpc-client-retry-works),
so a channel retry policy alone cannot replay this partially delivered stream.
The diagnostic records every ExecutePlan/ReattachExecute operation ID and resume
cursor, exact status/details, final unique ID set, every payload hash and exact
sum. No extra dependency, engine change or verification bypass is introduced.

# Sail streamed-result reset investigation — 2026-11-13

PR #5 remains a draft. The original qualification assertion and thresholds are
unchanged and blocking. No engine, production proxy profile, credential mode,
container hardening or verification policy is changed by this investigation.

## Root cause

**Downstream backpressure delays HTTP/2 keepalive progress on the NGINX → Sail
connection. Sail's 60-second PING / 10-second acknowledgement policy initiates
connection shutdown around 70 seconds; the paced client observes the failure
when it drains buffered responses around 80 seconds.** This is a transport
interaction between NGINX nonbuffered gRPC forwarding and Sail's Hyper/h2
keepalive accounting. It is not the profile's 3600-second timeouts, a fixed
80-second RPC limit, certificate verification or a Spark reattachment handoff.

The decisive native [run 43381217976](https://github.com/datopsis/sail-ubi/actions/runs/43381217976)
executes harness commit `04128a5` on
[amd64](https://github.com/datopsis/sail-ubi/actions/runs/43381217976/job/131739343721)
and [arm64](https://github.com/datopsis/sail-ubi/actions/runs/43381217976/job/131739343769).
Both actual job logs and retained artifacts were read. All eight passive
captures have zero packet drops and validated TCP/frame boundaries. Existing
runtime/hardening, publisher verification and both vulnerability scanners pass.
The original TLS coverage still records **33 PASS, one stream FAIL per architecture**.

| Diagnostic case | amd64 result | arm64 result |
| --- | --- | --- |
| Slow large: 1,000,000 rows; first 16 batches paced at 5 s | INTERNAL (13), 172,032 rows / 21 batches, 80.459 s | INTERNAL (13), 212,992 rows / 26 batches, 80.410 s |
| Fast large: same result, no sleeps | OK, 1,000,000 rows / 123 batches, 3.271 s | OK, 1,000,000 rows / 123 batches, 2.167 s |
| Slow small: 131,072 rows, same 5 s pacing | OK, 131,072 rows / 16 batches, 80.370 s | OK, 131,072 rows / 16 batches, 80.288 s |
| Steady large: same million rows, 0.7 s after each batch | OK, 1,000,000 rows / 123 batches, 88.478 s | OK, 1,000,000 rows / 123 batches, 87.799 s |

All successful results have exact ID sums and every SHA-512 payload verified.
The steady case is a diagnostic control, never a replacement for the blocking
slow-large qualification. Each case uses a fresh pair and changes only read
pacing or result size relative to the baseline.

## Evidence collection

`tests/stream_diagnostics.py` runs after the blocking TLS gate on native amd64
and arm64. Each experiment starts fresh restricted Sail and proxy containers,
per-run verified TLS and the pinned PySpark Connect client. The diagnostic proxy
configuration changes only `error_log /dev/stderr notice;` to `info;` in a
temporary copy. The approved repository/profile remains untouched. `nginx -V`
confirms this binary lacks `--with-debug`; `nginx -T` retains effective settings.
Sail transport logging uses `RUST_LOG` only in the diagnostic containers.

The client interceptor records ExecutePlan/ReattachExecute start/completion,
reattachable request options, gRPC status/details and wall/monotonic timestamps.
It returns the original gRPC call without wrapping or buffering its iterator.
Workload events retain elapsed time, verified row count and Arrow batch count.
The query is the gate's SHA-512 payload query, with exact hashes and ID sum.

A host observer enters only Sail's network namespace and passively records
loopback HTTP/2 control frames, DATA byte counts and TCP close events. It stores
no packet capture, DATA bodies, HPACK contents, TLS session keys or private keys.
Container users, capabilities, resource limits and read-only roots stay intact.
The observer checks zero packet drops and contiguous TCP reassembly. A TCP reset
that truncates a DATA frame is reported explicitly, requiring a matching reset
sequence and no gaps; missing packets or partial control frames still fail.
The encrypted frontend is not decrypted: its RST_STREAM code comes from the
actual gRPC client error, not an independent frontend frame capture.

## Initial reproduction

[Run 43378179524](https://github.com/datopsis/sail-ubi/actions/runs/43378179524)
reproduced the slow 1,000,000-row failure on both architectures. Both received
155,648 rows in 19 batches: amd64 80.346 seconds, arm64 80.334 seconds. The status
was gRPC **INTERNAL (13)**, with exact details:

```text
Stream removed (RST_STREAM (Received RST_STREAM with error code 2))
```

Both captures had zero dropped packets and no TCP sequence gaps. The observer
initially rejected the real reset-truncated DATA frame as incomplete reassembly,
so that run stopped before speed/size controls. Commit `4ca7bec` corrects this
classification and adds tests requiring a contiguous reset and DATA frame.
This does not change any qualification check.

NGINX reports `recv() failed (104: Connection reset by peer) while sending to
client`, naming the ExecutePlan upstream `grpc://127.0.0.1:50052`. Its access log
still shows HTTP 200 because response headers preceded the reset; HTTP 200 alone
is not a successful gRPC/result oracle. Sail's log shows session creation and
removal, with no process crash; its post-workload hardening probe and graceful
exit pass.

## Speed and result-size controls

[Run 43379762123](https://github.com/datopsis/sail-ubi/actions/runs/43379762123),
harness commit `4ca7bec`, completed all three diagnostics on native
[amd64](https://github.com/datopsis/sail-ubi/actions/runs/43379762123/job/131734781912)
and [arm64](https://github.com/datopsis/sail-ubi/actions/runs/43379762123/job/131734781901).
Actual logs and both evidence artifacts were inspected. All six captures passed
zero-drop and contiguous-reassembly checks. The separate original TLS stream gate
failed on both architectures; existing security gates passed.

| Case | Change from slow-large | amd64 | arm64 |
| --- | --- | --- | --- |
| Slow large | 1,000,000 rows; 5 s after first 16 batches | INTERNAL; 163,840 rows / 20 batches; 80.296 s | INTERNAL; 147,456 rows / 18 batches; 80.318 s |
| Fast large | Only pacing: no sleeps | OK; 1,000,000 rows / 123 batches; 2.109 s | OK; 1,000,000 rows / 123 batches; 2.172 s |
| Slow small | Only result size: 131,072 rows | OK; 131,072 rows / 16 batches; 80.238 s | OK; 131,072 rows / 16 batches; 80.290 s |

Successful cases verify every payload hash and the exact ID sum. Fast-large
transfers about 73.34 MB of gRPC DATA on each architecture. Slow-small transfers
9.61 MB, completing its proxy RPC at 45.138/45.160 seconds even though consuming
the buffered result takes 80 seconds. Thus slow-small alone does **not** establish
an active proxy RPC lasting 80 seconds. A separate steady-paced large control
addresses that distinction.

The slow-large amd64 backend sends **GOAWAY, error 0 (NO_ERROR), last stream 1**,
then FIN at 80.260 seconds after the ExecutePlan connection opens, without
finishing the result. NGINX logs `upstream prematurely closed connection` and the
client gets INTERNAL/RST_STREAM 2. The arm64 backend emits a delayed PING at
80.270 seconds, NGINX ACKs it 0.764 ms later, then Sail's TCP endpoint resets the
connection 0.132 ms after that ACK. Its partial DATA frame is explicitly recorded
(7,624 payload bytes received of 16,384). This run observes no backend HTTP/2
RST_STREAM in either case. These are two wire manifestations of backend closure;
NGINX's client-facing RST_STREAM 2 is not a backend RST_STREAM 2.

## Decisive transport timeline

The final slow-large run records NGINX repeatedly advertising a zero TCP receive
window to Sail between the client's reads. Sail's active stream logs:

```text
handle_error; err=GoAway(b"", NO_ERROR, User)
```

On amd64, the backend connection starts at **06:54:47.148 UTC** and this Sail log
appears at **06:55:57 UTC**. On arm64 it starts at **06:54:27.173 UTC** and the log
appears at **06:55:37 UTC**. Sail logs have one-second resolution: both are about
70 seconds after connection start. `User` is h2's local caller (Hyper), not the
remote Spark client. The pinned h2
[state handler](https://github.com/hyperium/h2/blob/v0.4.20/src/proto/streams/state.rs)
and [connection shutdown path](https://github.com/hyperium/h2/blob/v0.4.20/src/proto/connection.rs)
identify this as a locally initiated abrupt shutdown, while the pinned Hyper
server's keepalive-timeout branch requests exactly `NO_ERROR` shutdown.

The shutdown is initiated **before** the client-visible reset. On amd64 the
keepalive PING reaches loopback only at connection age **80.341 s**; NGINX ACKs
it at **80.376 s**, immediately followed by Sail's TCP RST. On arm64 no second
PING reaches the wire; **GOAWAY(0), last stream 1**, followed by FIN appears at
**80.292 s**. NGINX reports, respectively, `Connection reset by peer` and
`upstream prematurely closed connection`. Both clients receive the same exact
INTERNAL/RST_STREAM 2 details quoted below. No backend HTTP/2 RST_STREAM is
observed. The earlier run has the opposite architecture-to-wire-outcome mapping,
so this is not an architecture-specific defect.

Steady-large keeps the **actual proxy RPC** alive for **82.721 s amd64 /
82.068 s arm64**, transferring **73,339,903 / 73,339,930 DATA bytes**, with full
results and normal trailing HEADERS/END_STREAM. Its second backend PING reaches
the wire at **64.045 / 63.528 s**, with ACK at **67.642 / 66.381 s**. Both arrive
before the roughly 70-second shutdown deadline; neither Sail log contains the
local GoAway error. This isolates sustained duration from prolonged backpressure.

The wire observations establish blocked receive progress, late control frames,
backend-initiated closure and the successful duration control. The exact
60+10-second timer attribution combines these observations with Sail/Hyper/h2
source, rather than claiming an unavailable Hyper timer log was captured.

## Reattachment and retry boundary

The observed ExecutePlan request carries `reattachable=true`. That requests
result retention; it does not demonstrate a reattachment. Client RPC events and
proxy access logs show **no ReattachExecute** in the failing reproduction.
ReleaseExecute calls acknowledge consumed responses and are a different method.
There is no observed graceful end-of-stream handoff or max-duration reattachment.
The client has the same empty retry policy list as the original qualification.
Even the pinned client's default policy does not retry a generic INTERNAL/RST 2:
its INTERNAL retry branch requires `INVALID_CURSOR.DISCONNECTED` (or separate
server retry metadata). Retrying this error is not a proposed fix.

Source references used to interpret the evidence:

- [Sail's pinned server builder](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/server/builder.rs)
  configures 60-second HTTP/2 keepalive and a 10-second PONG timeout.
- [Hyper 1.12.0 keepalive](https://github.com/hyperium/hyper/blob/v1.12.0/src/proto/h2/ping.rs)
  starts the acknowledgement deadline when it queues a PING, without waiting
  for that frame to reach the peer. Its
  [server](https://github.com/hyperium/hyper/blob/v1.12.0/src/proto/h2/server.rs)
  requests abrupt shutdown when that deadline expires.
- [NGINX 1.30.6 gRPC module](https://github.com/nginx/nginx/blob/release-1.30.6/src/http/modules/ngx_http_grpc_module.c)
  advertises an upstream receive window of 2,147,483,647, uses nonbuffered
  forwarding and acknowledges PINGs when it parses them. The
  [upstream output loop](https://github.com/nginx/nginx/blob/release-1.30.6/src/http/ngx_http_upstream.c)
  can stop reading the backend while downstream output buffers remain busy.
- [Pinned PySpark 4.2.0 reattachment](https://github.com/apache/spark/blob/v4.2.0/python/pyspark/sql/connect/client/reattach.py)
  and [retry policy](https://github.com/apache/spark/blob/v4.2.0/python/pyspark/sql/connect/client/retries.py)
  distinguish graceful reattachment from this transport error.

## Ownership and qualification boundary

No production NGINX directive change is established as a fix by this evidence.
The approved `grpc_read_timeout`, `grpc_send_timeout`, `send_timeout` and
`client_body_timeout` remain 3600 seconds. `grpc_socket_keepalive` controls TCP
keepalive, not the HTTP/2 PING deadline. Increasing `grpc_buffer_size` to absorb
a bounded result would not establish correctness for larger or indefinitely
backpressured results; it is not proposed as a qualified fix. No buffer-size or
timeout workaround is applied.

The required follow-up is an owning-project transport fix that preserves
control-frame progress under downstream backpressure, or makes the server's
keepalive accounting tolerate a PING blocked before transmission. This PR does
not patch/rebuild Sail, upgrade it, modify nginx-ubi, retry away the failure, or
change the original workload. The coordinator must route any upstream fix and
rerun the unchanged qualification before admission.

This is a bounded native Docker diagnosis with synthetic rows and per-run PKI.
It does not qualify arbitrary idle durations, other clients, proxies or
orchestrators. Hyper's own keepalive trace messages are compiled behind an
optional feature absent from the pinned source lock; setting `RUST_LOG` cannot
add those messages to the shipped binary. The report distinguishes captured
wire events and emitted h2 logs from source-level interpretation. No tracing
rebuild or TLS-key capture is used.

Evidence is under `evidence/stream-diagnostics/`: `*-result.json`, client logs,
NGINX info/access logs, Sail logs, effective configuration, `nginx -V`, control
frame JSONL and observer integrity status. CI retains these artifacts for
14 days. The tables and source references here preserve the conclusions after
artifact expiry; generated raw evidence stays outside Git.

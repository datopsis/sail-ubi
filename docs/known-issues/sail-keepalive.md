# Draft upstream feature request: configurable Spark Connect HTTP/2 keepalive

**Draft only — not filed.** The owner decides whether and where to submit this
request. This document does not change Sail 0.7.3, nginx-ubi or their pins.

## Suggested title

Expose Spark Connect server HTTP/2 keepalive interval and acknowledgement timeout

## Request

Please expose the gRPC server's HTTP/2 keepalive interval and acknowledgement
timeout through supported Sail application configuration/environment variables.
Retain the current defaults for compatibility, validate duration values, document
their units, and consider an explicit disabled-interval representation consistent
with tonic's optional interval. Configuration names and disable semantics are for
upstream maintainers to decide; no proposed key is presented here as supported.

The shipped 0.7.3 binary has no supported way to adjust these settings. This is
an availability/interoperability request, not a request for a native TLS listener,
weaker TLS verification, client authentication or a different credential mode.

## Pinned source

Sail source commit: `ac4690078021cf2a5402dc5c7b38a886f1916c73`.

- [Builder defaults, lines 24–32](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/server/builder.rs#L24-L32)
  set a 60-second HTTP/2 interval and 10-second acknowledgement timeout.
- [Tonic configuration, lines 64–69](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/server/builder.rs#L64-L69)
  applies those values.
- [Spark Connect entrypoint, lines 49–67](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-spark-connect/src/entrypoint.rs#L49-L67)
  passes `Default::default()` directly to `ServerBuilder::new`.
- [Environment mapping, lines 74–82](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/config/application.rs#L74-L82)
  maps `SAIL_` variables into application configuration. The
  [Spark config, lines 949–954](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/config/application.rs#L949-L954)
  exposes session timeout and application heartbeat interval, not HTTP/2 keepalive.

## Reproduction and observed outcome

Use the shipped Sail 0.7.3 wheel, pyspark-client 4.2.0, and nginx-ubi profile at
`9ef9e822c6b5e508cebef2adff3bb647a206773c` (NGINX 1.30.6):

1. Sail listens only on `127.0.0.1:50052`. NGINX shares its network namespace,
   serves verified TLS HTTP/2 on 50051 and uses `grpc_pass grpc://127.0.0.1:50052`.
   All four relevant proxy read/send/body timeouts are 3600 seconds.
2. Query `spark.range(1_000_000).selectExpr('id', 'sha2(CAST(id AS STRING), 512) AS payload')`.
   Consume Arrow batches and sleep five seconds after each of the first 16.
3. With the default client policy, observe partial results and gRPC INTERNAL
   (13), with exact details:

   ```text
   Stream removed (RST_STREAM (Received RST_STREAM with error code 2))
   ```

Native [run 43383736530](https://github.com/datopsis/sail-ubi/actions/runs/43383736530)
used harness commit `32713fe`. On
[amd64](https://github.com/datopsis/sail-ubi/actions/runs/43383736530/job/131747571962)
and [arm64](https://github.com/datopsis/sail-ubi/actions/runs/43383736530/job/131747572069),
the default client received 163,840 rows / 20 batches before failing at
80.302 / 80.342 seconds. A narrowly matched custom PySpark policy then proved
complete recovery on fresh pairs via one ReattachExecute, same operation ID and
a resume cursor: 1,000,000 unique IDs, every hash and exact sum 499999500000,
in 83.021 / 83.188 seconds. The underlying transport still resets.

The [diagnostic run](https://github.com/datopsis/sail-ubi/actions/runs/43381217976)
shows NGINX advertising zero TCP receive windows while the consumer is slow,
Sail logging local `GoAway(b"", NO_ERROR, User)` near 70 seconds, and late PINGs
or GOAWAY(0)/FIN/TCP reset near 80 seconds. Captures have zero dropped packets.
A steady-paced million-row control succeeds with actual proxy RPC durations
82.721 / 82.068 seconds and timely PING acknowledgements. Fast consumption also
succeeds. `grpc_buffer_size 64k;` and `1m;` do not fix the original slow case.

The timer attribution combines captured events with the
[Hyper keepalive scheduling](https://github.com/hyperium/hyper/blob/v1.12.0/src/proto/h2/ping.rs)
and [timeout shutdown](https://github.com/hyperium/hyper/blob/v1.12.0/src/proto/h2/server.rs)
source. A PING's acknowledgement deadline can begin while downstream
backpressure delays its transmission/processing. Hyper's own timer trace was
not available in this shipped build. The frontend TLS stream was not decrypted.

## Why configurability helps

Operators currently cannot align server keepalive policy with a deployment's
backpressure behavior without rebuilding Sail or requiring a custom client
recovery policy. Exposing the existing builder options would make that choice
explicit and testable. It would not by itself prove that any particular timeout
solves arbitrary slow-consumer behavior; the upstream implementation may also
need to distinguish a queued PING from one actually transmitted.

Suggested validation: preserve default behavior; demonstrate that supported
configuration reaches the tonic builder; reject invalid values; test long
backpressured results and PING progress with exact result integrity. Include
native amd64/arm64 coverage where practical. This request does not prescribe
unverified deployment values or claim that disabling keepalive is universally
appropriate.

Our owner chose document + retry + upstream on 2026-11-13. The local contract is
an exact-default-failure canary plus blocking complete client recovery. Repeated
drops, server restart, retention expiry and mutating SQL remain untested. See
[the diagnosis](../evals/2026-11-13-sail-stream-reset.md),
[fix-option results](../evals/2026-11-13-sail-stream-fix-options.md) and
[current client policy/checks](../TLS.md). CI artifacts expire after 14 days;
these documents retain the measured outcomes and source references.

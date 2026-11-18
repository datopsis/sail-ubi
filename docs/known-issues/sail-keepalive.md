# Upstream issue proposal: configurable Spark Connect HTTP/2 keepalive

**Ready for owner review; not filed.** Checked upstream main on 2026-11-18 at
`1abe463243dc6252368a82f278b5d84e842d5347`. The configuration gap remains:
60-second HTTP/2 keepalive interval and 10-second acknowledgement timeout are
still passed as builder defaults. No main runtime reproduction was performed.
This document changes no Sail 0.7.3, proxy, client or image pins.

Suggested title: **Expose Spark Connect HTTP/2 keepalive interval and ACK timeout**

The following is the proposed issue body. Links to local evidence use full GitHub
URLs so the text can be submitted without repairing repository-relative links.

```draft
Please expose Spark Connect server HTTP/2 keepalive settings in Sail application configuration, retaining today's defaults. We can send a small PR if this direction is welcome.

### Current main still uses fixed defaults

Checked main at `1abe463243dc6252368a82f278b5d84e842d5347` on 2026-11-18:

- [ServerBuilderOptions defaults, builder.rs:26–38](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-common/src/server/builder.rs#L26-L38): HTTP/2 interval 60 seconds, ACK timeout 10 seconds.
- [Tonic wiring, builder.rs:68–75](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-common/src/server/builder.rs#L68-L75): applies those values, separately from TCP keepalive.
- [Connect entrypoint:49–69](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-spark-connect/src/entrypoint.rs#L49-L69): calls ServerBuilder with `Default::default()`.
- [SparkConfig:978–984](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-common/src/config/application.rs#L978-L984): exposes session timeout and execution heartbeat, not transport keepalive. [AppConfig loading:74–83](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-common/src/config/application.rs#L74-L83) maps `SAIL_` environment variables with `__` nesting.

The [Spark 4.3 configuration data:98–114](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-spark-connect/data/config/spark-4.3.json#L98-L114) contains keepalive descriptions. That metadata does not wire the values to this server builder. Source searches across application configuration, Connect implementation and docs found no supported override. The Rust builder fields are not application settings of the shipped binary.

For comparison, [0.7.3 defaults:24–32](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/server/builder.rs#L24-L32) and [entrypoint:49–67](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-spark-connect/src/entrypoint.rs#L49-L67) use the same interval/timeout and default wiring. Main has additional HTTP/2 window options; this is not evidence that the keepalive configuration gap is fixed.

### Reproduction on Sail 0.7.3

Environment: shipped Sail 0.7.3 wheel, pyspark-client 4.2.0, native Linux amd64 and arm64, NGINX 1.30.6 from [nginx-ubi profile commit 9ef9e822](https://github.com/datopsis/nginx-ubi/blob/9ef9e822c6b5e508cebef2adff3bb647a206773c/examples/profiles/sail/nginx.conf).

1. Sail listens on `127.0.0.1:50052`. NGINX shares its network namespace, serves verified TLS HTTP/2 on 50051 and forwards with `grpc_pass grpc://127.0.0.1:50052`. Proxy read/send/body timeouts are 3600 seconds.
2. Run the following with the default client retry policy and a fresh connection:

~~~python
import time
import pyarrow as pa
from pyspark.sql import SparkSession

# Set GRPC_DEFAULT_SSL_ROOTS_FILE_PATH to the public CA before starting Python.
spark = SparkSession.builder.remote(
    "sc://localhost:50051/;use_ssl=true"
).getOrCreate()
try:
    frame = spark.range(1_000_000).selectExpr(
        "id", "sha2(CAST(id AS STRING), 512) AS payload"
    )
    rows = batches = 0
    # Iterator and plan API are specific to the pinned diagnostic client.
    plan = frame._plan.to_proto(spark.client)
    for table in spark.client.to_table_as_iterator(plan, {}):
        if not isinstance(table, pa.Table):
            continue
        rows += table.num_rows
        batches += 1
        if batches <= 16:
            time.sleep(5)
    print(rows)
finally:
    spark.stop()
~~~

Expected: all 1,000,000 rows while the consumer progresses. Observed: partial rows then INTERNAL (13), `Stream removed (RST_STREAM (Received RST_STREAM with error code 2))`, near 80 seconds.

[Native run 43383736530](https://github.com/datopsis/sail-ubi/actions/runs/43383736530), harness `32713fe`, recorded 163,840 rows / 20 batches on each architecture, failing at 80.302 / 80.342 seconds. A separate narrow client policy recovered complete results with one ReattachExecute, but did not prevent the reset. These are historical recorded measurements, not a rerun against main.

The [diagnostic report](https://github.com/datopsis/sail-ubi/blob/e96e068f926b8fecb3939e953389685ee4780032/docs/evals/2026-11-13-sail-stream-reset.md) records zero-window backpressure, local Sail GoAway(NO_ERROR, User) near 70 seconds, and late PING or GOAWAY/FIN/reset near 80 seconds. Fast consumers succeeded; steady consumers sustained actual proxy RPCs beyond 82 seconds. [64k and 1m proxy buffers both failed](https://github.com/datopsis/sail-ubi/blob/e96e068f926b8fecb3939e953389685ee4780032/docs/evals/2026-11-13-sail-stream-fix-options.md).

The 60+10-second attribution combines captured events with [Hyper keepalive scheduling](https://github.com/hyperium/hyper/blob/v1.12.0/src/proto/h2/ping.rs) and [timeout shutdown](https://github.com/hyperium/hyper/blob/v1.12.0/src/proto/h2/server.rs): the ACK deadline can run while a queued PING is blocked. Hyper timer tracing was unavailable and frontend TLS was not decrypted. CI raw artifacts have a 14-day retention; the linked reports preserve outcomes and limits.

### Minimal proposed change

Proposed names, not currently supported settings:

| Application key | Environment variable | Default / semantics |
| --- | --- | --- |
| `spark.http2_keepalive_enabled` | `SAIL_SPARK__HTTP2_KEEPALIVE_ENABLED` | `true`; false maps interval to None |
| `spark.http2_keepalive_interval_secs` | `SAIL_SPARK__HTTP2_KEEPALIVE_INTERVAL_SECS` | `60`; positive whole seconds |
| `spark.http2_keepalive_timeout_secs` | `SAIL_SPARK__HTTP2_KEEPALIVE_TIMEOUT_SECS` | `10`; positive whole seconds |

Add defaults/schema/docs, validate positive representable durations (including when disabled), and pass these fields into ServerBuilderOptions at Connect startup, leaving all other defaults unchanged. An explicit enable flag avoids overloading zero with both invalid and disabled meanings. These are server startup settings, never mutable session Spark conf. Keep session timeout, execution heartbeat and TCP keepalive independent.

Tests: omitted settings produce exactly today's builder options; each override reaches tonic; disabling produces no interval; reject malformed, negative, zero and overflowing durations. Rerun the slow-result workload with exact ID/hash/sum integrity and observe PING progress for candidate settings. No particular replacement value or universal fix is claimed: configurability permits deployment testing, while transport-level queued-versus-transmitted PING accounting may still need attention.

We would be happy to send a PR with backward-compatible defaults and focused tests. This request does not require changes to TLS verification, authentication, proxy buffering or the engine version.
```

## Owner verification notes

Source inspection establishes the missing configuration on pinned main, not
whether newer Hyper/h2 behavior changes the runtime symptom. The reproduction
snippet follows the existing pinned-client Arrow iteration harness; it was not
executed in this documentation task. The original captures and CI logs were not
re-downloaded here; measurements are attributed to the committed evaluation
reports. Repeated drops, restart, retention expiry and mutating SQL remain
unqualified. No upstream submission or maintainer contact occurred.

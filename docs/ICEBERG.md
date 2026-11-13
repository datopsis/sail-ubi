# Iceberg / Lakekeeper readiness at Sail 0.7.3

For Phase A transport, use the HTTPS endpoints and shared-namespace loopback
deployment in [TLS.md](TLS.md), subject to its native qualification results.
The HTTP/remote-bind examples below describe the earlier isolated startup test,
not Phase A. TLS qualification does not change static AWS credentials or the
pinned engine's delegation header; the historical no-vending-header limitation
below is distinct from qualifying transport for the owner-selected static path.

**The pinned engine cannot omit its vended-credentials request header.** That
limitation is distinct from static S3 signing, which the Phase A transport fixture
proves. Do not admit it as a working Lakekeeper engine based on the startup or
transport tests. No upstream upgrade or credential-mode change is made here.

## Version and support evidence

`artifacts/sail.lock.json` pins pysail **0.7.3**, commit
`ac4690078021cf2a5402dc5c7b38a886f1916c73`, on both architectures. These conclusions
come from that commit's docs, implementation and upstream tests, not from `main`.
They are upstream capabilities, not results of running the Datopsis integration.

| Capability | Pinned 0.7.3 |
| --- | --- |
| `iceberg-rest` catalog | Yes; `SAIL_CATALOG__LIST` contains a TOML array of inline tables |
| Iceberg reads | Yes; Parquet, including v2 position/equality deletes |
| `CREATE TABLE`, CTAS, `INSERT` | Yes; REST catalog creation and commits implemented; v2 is the default |
| `UPDATE`, `DELETE`, `MERGE INTO` | Yes with default copy-on-write; see merge-on-read limits below |
| Static S3 credentials | Yes; AWS environment or shared credentials file |
| Custom S3 endpoint / region / HTTP | Yes; `AWS_ENDPOINT`, `AWS_REGION`, `AWS_ALLOW_HTTP` |
| Path-style S3 | Yes; `AWS_VIRTUAL_HOSTED_STYLE_REQUEST=false` |
| Disable `vended-credentials` delegation | **No**; the table-access request hard-codes the header |
| This Lakekeeper + SeaweedFS setup | Interoperability unverified here; a profile requiring delegation-header omission remains unsupported |

In v2 merge-on-read, `UPDATE` is unsupported; `DELETE` writes equality deletes
only for unpartitioned tables with supported field types; `MERGE INTO` uses
position deletes. Default copy-on-write is the appropriate initial mutation
path. Do not infer Trino's snapshot operation sequence for Sail.

Pinned references:

- [REST catalog options](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/docs/guide/catalog/iceberg-rest.md),
  [configuration enum](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-common/src/config/application.rs#L853),
  [provider construction](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-session/src/catalog.rs#L48).
- [Iceberg feature matrix](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/docs/guide/sources/iceberg/features.md),
  [REST write/delete/merge tests](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/python/pysail/tests/spark/catalog/iceberg_rest/test_commit.py).
- [S3 docs](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/docs/guide/storage/s3.md),
  [S3 client initialization](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-object-store/src/s3.rs#L105),
  [upstream Lakekeeper test with static S3 and path-style](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/python/pysail/tests/spark/catalog/iceberg_rest/test_lakekeeper.py#L19).
- [`begin_table_access` hard-coded delegation](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/crates/sail-catalog-iceberg/src/provider.rs#L1623).
  The same code explicitly notes that REST session credentials are not yet
  converted to operation-scoped object-store credentials. Supplying static AWS
  credentials does not change the REST request header.

`access_delegation` was added by upstream
[commit 0c8333a349e5438e4b37fe984b9e3a45befc7bff / PR #2920](https://github.com/lakehq/sail/commit/0c8333a349e5438e4b37fe984b9e3a45befc7bff),
nine commits after v0.7.3. As checked on 2026-11-11, the latest release and highest
version tag are still v0.7.3: **no released version yet contains this option**.
Do not claim that 0.7.4 contains it before a release exists. The future option
`access_delegation="none"` (or an empty string) omits the header; the underlying
REST property is `access-delegation`. Leaving the option unset requests vending.

## Exact deployment configuration

For startup on the pinned image with this change, supply:

```sh
export SAIL_CATALOG__LIST='[{type="iceberg-rest", name="qualification", uri="http://catalog:8181/catalog", warehouse="qualification"}]'
export AWS_ENDPOINT='http://s3:8333'
export AWS_REGION='local'
export AWS_ALLOW_HTTP='true'
export AWS_VIRTUAL_HOSTED_STYLE_REQUEST='false'
```

The sole catalog becomes the default; use names such as
`qualification.<namespace>.<table>`. Catalog and warehouse names are distinct
concepts even though both use `qualification` here. The warehouse is a Lakekeeper
name, not `s3://warehouse`. No catalog token/login configuration is supplied.

Inject `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` from the harness's generated,
Sail-only environment file. With Docker, use `--env-file` for that file (never
commit or upload it); with Compose, use a service-specific `env_file`. Pass the
non-secret variables above into the container too. No AWS secret values belong
in Compose, command arguments, examples or image layers. Alternatively mount a
Sail-only AWS shared credentials file read-only and set
`AWS_SHARED_CREDENTIALS_FILE=/run/secrets/sail/aws-credentials`; its `[default]`
profile uses `aws_access_key_id` and `aws_secret_access_key`. The file must be
readable by UID 10001. Do not mount other services' secrets. The runtime test
exercises the environment route; shared-file credential resolution is upstream
supported but not exercised here. No `_FILE` suffix for individual AWS keys is
implemented by this image.

**No 0.7.3 configuration can omit the delegation request header.** This does not
prevent the independently tested static S3 path. Once
a separately reviewed upgrade includes upstream #2920, the intended catalog
value is the following; this is not a supported 0.7.3 configuration:

```sh
export SAIL_CATALOG__LIST='[{type="iceberg-rest", name="qualification", uri="http://catalog:8181/catalog", warehouse="qualification", access_delegation="none"}]'
```

Keep the existing read-only `/etc/sail/config.json` listener configuration,
UID/GID `10001:10001`, read-only root, dropped capabilities, no-new-privileges,
and the two existing writable mounts `/tmp` and `/var/lib/sail`. A separate
integration client needs `bind="0.0.0.0"`, port 50051 and
`allow_unauthenticated_remote=true` in that JSON file, on the integration's
private internal network with no published port. This remains the documented
unauthenticated isolated-test opt-out, not production authentication.

Only the exact `SAIL_CATALOG__LIST` variable is newly admitted. Group-level
`SAIL_CATALOG`, default-catalog overrides, and all role/runtime/telemetry
overrides remain rejected. Upstream parses the catalog value. AWS environment
variables already pass through; no dependency or writable directory is added.

## Qualification boundary and integration handoff

The native runtime test injects the REST catalog and freshly generated S3
credentials through environment variables. It asserts `SHOW CATALOGS` contains
`qualification` and `current_catalog()` selects it, then runs the existing
SQL/DataFrame/local Parquet tests, repeats the process hardening probes, and
requires clean shutdown. It asserts server logs do not contain the generated
keys. TCP readiness alone would not prove catalog registration.

This test makes **no Lakekeeper or S3 requests**. It does not verify S3 signing,
Lakekeeper table creation/commits, cross-engine rows, deletion-file decoding,
restarts, or actual UPDATE/DELETE/MERGE interoperability. Those are required
future integration evidence. A profile forbidding the delegation request header
additionally requires resolution of that upstream limitation.

Context was read at lakehouse-integration commit
[`e93081a9c60030ee9313acc9e32e7e1efe66a4a6`](https://github.com/datopsis/lakehouse-integration/tree/e93081a9c60030ee9313acc9e32e7e1efe66a4a6).
Its per-service secrets, static S3 main path, Lakekeeper login-off gap, strict
revision/artifact-lock provenance, and full-SHA image pins remain binding. Keep
Trino's `parquet.writer.delta-length-byte-array-encoding-enabled=false` and its
separate canary unchanged. Pin a reviewed Sail image source commit only after
the integration independently checks its provenance and actual behavior.

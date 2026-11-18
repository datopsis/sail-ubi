# Proposal: immutable per-session Iceberg REST catalog identity

**Owner review only; not submitted upstream.** Researched 2026-11-18 against
Sail `main` at `1abe463243dc6252368a82f278b5d84e842d5347` (Apache-2.0).
This proposes upstream work, not a supported configuration or an engine upgrade.
Our deployed input remains Sail 0.7.3 at
`ac4690078021cf2a5402dc5c7b38a886f1916c73`.

## Motivation and scope

Our governed lakehouse puts Sail behind our authorization gateway, using Rauthy
OpenID tokens, Lakekeeper's Iceberg REST catalog with per-user permissions, and
SeaweedFS S3. With a fixed catalog credential, all clients of one Sail server
reach Lakekeeper as the same identity. Gateway admission alone cannot make
Lakekeeper apply each user's catalog grants or attribute catalog actions to that
user. We need distinct catalog authorization and audit for interactive analysts,
service identities, and concurrent applications using the same static warehouse.
A catalog token must be suitable for Lakekeeper; an OpenID ID token or a token
issued only for the gateway is not automatically a catalog access token.

In [#2929](https://github.com/lakehq/sail/pull/2929), dynamic session catalog
registration through Spark configuration was declined. On
[2026-11-04, linhr explained](https://github.com/lakehq/sail/pull/2929#issuecomment-6625018093)
that partial configuration changes can affect concurrent queries within a
session and that mutable catalogs create unclear behavior. He recommended
lightweight separate servers per client while gathering feedback. The author
[accepted that guidance](https://github.com/lakehq/sail/pull/2929#issuecomment-6625442327).
We reviewed the full PR body and both issue comments using the issues API and
its paginated comments endpoint. This proposal is feedback on identity, and
preserves the static catalog model.

Separate processes are a valid baseline and provide a stronger isolation
boundary. At high client counts, potential costs include idle RSS, startup and
TLS/catalog bootstrap work, connections, scheduling, routing and process churn.
These are hypotheses, not measured objections to Sail's lightweight design.
**Spike S5 measurements pending:** `[insert revision, hardware, client counts,
idle/active RSS, startup median/p95, throughput, connection count and lifecycle
cost for per-client servers versus shared sessions]`. No S5 numbers are available
in this repository; adoption should depend on that comparison.

This is catalog identity isolation, not complete hostile SQL tenant isolation.
SQL filesystem access, direct S3 reads, UDF execution, shared memory/CPU, spill
and distributed workers require separate controls. The existing Phase A fixtures
prove bounded transport behavior, not Rauthy/Lakekeeper/SeaweedFS authorization.

## Source map at the pinned main commit

All source links below are immutable permalinks. Observations describe current
code; subsequent sections describe proposed behavior.

| Area | Evidence and implication |
| --- | --- |
| Configuration | [`AppConfig::load`, application.rs:74–83](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-common/src/config/application.rs#L74-L83) merges compiled configuration, internal placeholders and `SAIL_` environment variables, replacing `__` with `.`. [Iceberg options:867–923](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-common/src/config/application.rs#L867-L923) describe server-owned endpoint, warehouse, credentials, delegation and signing. Tokens/passwords use `SecretString` and secret serialization. |
| gRPC boundary | [`server.rs:146–169`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-spark-connect/src/server.rs#L146-L169) receives a tonic `Request`, discards its envelope with `into_inner()`, and derives `user_id` from client protobuf `user_context`. This is not authenticated identity. Other handlers repeat this pattern. [`TracingServerLayer`:39–52](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-common/src/telemetry/layers/server.rs#L39-L52) reads HTTP `traceparent`, not authorization. Metadata must be authenticated/extracted before the envelope is discarded. |
| Session key and creation | [`SessionKey`:7–11](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-session/src/session_manager/session.rs#L7-L11) contains user ID and client session ID. [`handler.rs:36–68`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-session/src/session_manager/actor/handler.rs#L36-L68) reuses a running context, queues creation waiters, or assigns a new server UUID. Creation is lazy on an RPC, not a dedicated authenticated CreateSession handshake. |
| Lifecycle | [`handler.rs:132–235`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-session/src/session_manager/actor/handler.rs#L132-L235) constructs context, inserts Creating state and publishes Running after activation. [Idle/delete paths:265–349](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-session/src/session_manager/actor/handler.rs#L265-L349) mark sessions deleted; [cleanup:392–409](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-session/src/session_manager/actor/handler.rs#L392-L409) stops tasks and cleans checkpoints. [ReleaseSession:503–524](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-spark-connect/src/server.rs#L503-L524) rejects reconnect; [CloneSession:536–543](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-spark-connect/src/server.rs#L536-L543) is unimplemented. |
| Catalog ownership | [`ServerSessionFactory`:58–79,104–139](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-session/src/session_factory/server.rs#L58-L139) retains one application config and global cache manager, constructing a catalog manager per session. [`CatalogManager`:19–69](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-catalog/src/manager/mod.rs#L19-L69) owns a mutex-protected provider map and session defaults. [`catalog.rs:26–120`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-session/src/catalog.rs#L26-L120) builds providers from the static application list. A per-session provider already exists; a per-session authenticated credential input does not. |
| Credential abstraction | [`credentials.rs:9–129`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-catalog/src/credentials.rs#L9-L129) defines async `retrieve()` and a default Bearer scheme. Empty returns none; static returns a cloned token with redacted Debug; Basic returns encoded username/password with redacted Debug and Basic scheme; file reads and trims a server path each call. File credentials rotate and are not an immutable session snapshot. |
| Credential selection | [`catalog.rs:339–386`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-session/src/catalog.rs#L339-L386) rejects incomplete Basic settings or Basic combined with tokens. Otherwise file wins, then bearer, then OAuth token, then empty. This is server configuration, not session identity. |
| Per-request REST auth | [`provider.rs:175–284`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-catalog-iceberg/src/provider.rs#L175-L284) retrieves credentials while constructing each bootstrap/request client and retries once on 401 with another retrieval. Shared HTTP transport does not require shared credentials. [Resolved configuration:298–333](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-catalog-iceberg/src/provider.rs#L298-L333) is a provider-local OnceCell populated by `/v1/config`, merging server defaults, local properties, then server overrides. |
| SigV4 | [`catalog.rs:94–108`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-session/src/catalog.rs#L94-L108) independently enables signing. [`sigv4_state.rs:38–95`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-catalog-iceberg/src/sigv4_state.rs#L38-L95) uses the AWS provider chain and identity cache; SigV4 is not another `CatalogCredentials` implementation. [`sigv4.rs:120–141`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-catalog-iceberg/src/sigv4.rs#L120-L141) describes moving existing auth to `Original-Authorization`, redirect and trace risks. [Provider:156–171](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-catalog-iceberg/src/provider.rs#L156-L171) disables redirects for signed requests. |
| Catalog cache keys | [`provider/cache.rs:24–62`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-catalog/src/provider/cache.rs#L24-L62) maps catalog name to bundles; inside a bundle database listings use `Option<Namespace>`, table/view listings use `Namespace`. [`catalog.rs:303–336`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-session/src/catalog.rs#L303-L336) attaches global bundles by name. No user/session discriminator exists there. [Session caches:73–127](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-catalog/src/provider/cache.rs#L73-L127) instead allocate per provider. |
| Other shared caches | [`runtime.rs:101–173`](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-session/src/runtime.rs#L101-L173) can reuse global listing/statistics/metadata caches. [File metadata:11–14](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-cache/src/file_metadata_cache.rs#L11-L14) uses object `Path`; [statistics:11–12](https://github.com/lakehq/sail/blob/1abe463243dc6252368a82f278b5d84e842d5347/crates/sail-cache/src/file_statistics_cache.rs#L11-L12) uses `TableScopedPath`. These are not authenticated principal keys. |

Basic and SigV4 support on this main snapshot do not establish end-user identity
propagation. Likewise, the existing file rotation behavior must not be reused as
a way to swap one shared file between users.

## Alternatives

| Alternative | Benefits | Costs, risks and constraints |
| --- | --- | --- |
| A. Separate Sail server per client, as recommended by linhr | Works with static configuration today; simple lifecycle; separate processes and credentials; strongest baseline for resource and failure isolation. | Routing, process startup, per-process memory and idle capacity may matter at scale; quantify with S5. Needs safe credential provisioning and refresh per instance. Multiple users must never share an instance credential accidentally. |
| B. Per-session `CatalogCredentials`, resolved from authenticated session metadata | Reuses the async credential seam and session-owned providers; one static catalog definition; queries see one immutable credential; avoids a process per application. | Requires a trustworthy metadata boundary, authentication on every RPC, ownership checks on every session operation, cache partitioning and expiry enforcement. Shares a process, so is not a hostile-tenant sandbox. A gateway-provided credential must have the catalog's audience. |
| C. Server-controlled token-exchange hook at session creation | Converts an authenticated subject token into a short-lived catalog/audience-scoped token; avoids forwarding gateway-only tokens; can narrow warehouse/scope. Can feed the same immutable provider as B. | Adds an authorization service, latency, availability dependency, delegated authority and secret handling. Issuer, endpoint, scopes and audience must be operator-owned. A permissive hook becomes a confused deputy. Exchange protocol and Rauthy/Lakekeeper interoperability need verification. |

**Recommendation:** keep A as the supported baseline; seek agreement on B as a
narrow opt-in extension, initially for gateway-authenticated local-mode servers
and Bearer catalog credentials only. Let operators perform exchange at their
gateway initially. C can later implement the same creation-time resolver
interface if demand justifies upstream protocol support. Do not add a general
plugin framework, dynamic catalog registration or token refresh protocol first.

## Proposed contract

### Static catalog, one immutable binding

An operator enables session identity explicitly, default **off**, and chooses
which statically named Iceberg catalog requires it. Endpoint, warehouse, prefix,
delegation policy, TLS roots, signing settings and catalog type stay in server
configuration. Reject conflicting static/file/Basic credentials for that catalog
when session identity is enabled; never silently fall back to a service token.
Names and configuration schema below are design concepts, not existing options.

An authentication boundary turns gRPC metadata into a typed, redacted
`AuthenticatedSessionIdentity`: validated issuer, subject, tenant, catalog audience,
expiry and secret catalog token. Initial mode trusts only an authenticated,
operator-designated gateway channel (for example mTLS or an authenticated local
transport protected from other processes). Strip client-supplied internal identity
headers at the gateway and inject its own assertions. A raw forwarded
`x-user-id`, protobuf `user_context.user_id`, session UUID, or unverified Bearer
header is insufficient. Network restriction alone must not be described as
cryptographic peer authentication. This requires deployment qualification beyond
our current Phase A server-TLS-only profile.

Before `into_inner()`, extract/verify the assertion, reject duplicate/oversized or
malformed credentials, and put only the typed identity in request extensions.
If Sail validates signed assertions directly, pin allowed issuer/keys, algorithms,
audiences and clock skew in operator policy; never fetch a client-selected JWKS
URL. Define the gateway assertion format and verification adapter with maintainers
before implementation. Do not assume Sail currently authenticates OpenID tokens.

On the first session-creating RPC, reserve the session key and install the full
identity and credential atomically before constructing the CatalogManager or
publishing Running. Key lookup by `(validated issuer, tenant, subject,
client_session_id)`; use a fresh server session UUID as an incarnation boundary.
Do not use the client protobuf user ID as the authorization key. Concurrent
first RPCs must join one creation only if their authenticated binding matches;
a different credential/binding for the same live session is rejected. If an
async resolver is needed, reserve Creating before awaiting it; failure wakes all
waiters and releases secrets without publishing a partial session.

Construct a session-owned `Arc<dyn CatalogCredentials>` from the immutable
snapshot, returning that same token on each `retrieve()`. The REST provider's
per-request retrieval and 401 retry never rotate it. Do not implement SET/Config
as a binding path. A second bind, token replacement, or changed principal is
rejected explicitly even if it arrives while no query is running. Return a
sanitized session-expired/binding-mismatch error with a stable documented code.

Authenticate **every RPC** and check ownership of its session and operation:
ExecutePlan, AnalyzePlan, Config, artifact upload, interrupt, release, reattach,
and any future clone/status/error-details method. Preserve and validate the
client-observed server session ID; operation IDs and cursors are never authority.
A reconnect/reattach may resume only the same live session and binding, not copy
results into a newly authenticated session. Transport reconnection alone does
not create a new identity. Never carry tokens in query tags or protobuf user IDs.

### Expiry and refresh: new session only

Choose a new session for refresh. The bound catalog token is never replaced and
no refresh token is retained in Sail. Enforce a known expiry from a trusted
assertion or trusted token validation; opaque tokens need an operator-bounded
session deadline supplied by the gateway. Deadline is the earlier of credential
expiry and configured maximum session lifetime, with bounded clock skew.

Reject new work and reattachment after expiry; cancel active work at the deadline,
stop outbound credential use, close result delivery and release session caches
and retained results. An RPC admitted before expiry cannot keep using a cached
table/provider indefinitely. Cancellation is best effort: an already dispatched
catalog request/commit may finish, and buffered bytes cannot be recalled. Do not
promise instantaneous revocation or rollback. A remote 401/403 fails closed
(after at most the existing bounded same-token 401 retry), with no escalation or
service-credential fallback. Permission revocation before expiry remains the
catalog/storage authority's responsibility; do not claim cached authorization
is immediately revoked.

Clients obtain a fresh gateway/catalog credential and use a **new client session
ID**. Temporary views, configuration and cursors do not migrate automatically;
never replay a mutation just to renew authentication. This is less convenient
for long jobs but gives one unambiguous credential lifetime across concurrent
queries and avoids the quiescence/reattachment races of secure re-bind. A future
re-bind would need a drain barrier covering all queries, retained results and
outbound operations, then a new incarnation/cache scope; it is out of scope.

### Cache and downstream boundaries

For the initial opt-in mode, reject global catalog and global file cache settings
at startup. Require session or disabled caches, including listing, statistics
and metadata caches in the runtime. Do not silently reinterpret an operator's
explicit global policy. A session-owned provider's OnceCell, auth client headers,
table handles, plans, vended credentials, object stores and retained results must
stay in that session's scope. Disable any remaining shared cache whose scope
cannot be established in the implementation audit.

Within private caches the effective key is `(server_session_incarnation,
static_catalog_id, object_key)` by ownership; nested namespace keys are safe only
inside that private container. If a shared cache is later necessary, include
incarnation and validated principal/tenant plus catalog identity and object key
explicitly. Username, catalog name, table path or token hash alone is insufficient.
Do not use raw tokens as keys or metric labels. Evict on deletion, expiry and
failed creation; wait for task shutdown before dropping credential-owning state.

Plain HTTP connection pools may be shared only if they hold no default auth,
cookies or per-user state and attach credentials per request. Share no provider
or authenticated client state between sessions. Check REST `/v1/config` overrides
and redirects against the server's allowed origins before forwarding credentials;
reject redirects in session-token mode, including unsigned REST calls. No
client-chosen URI, file path, token endpoint, proxy, warehouse or signing target.

Catalog authorization alone does not secure SeaweedFS data: shared static S3
credentials may let SQL bypass catalog permissions through direct paths. Before
production use, establish operation/session-scoped least-privilege storage
credentials and prevent unauthorized direct-path access. Initially reject
session-identity configurations that would claim user data isolation while
retaining unrestricted shared storage access. Keep catalog identity and AWS
SigV4 identity distinct; do not turn the server AWS role into an implicit user.
General distributed credential propagation and worker isolation are deferred;
fail closed for this opt-in mode outside qualified local execution.

## Security review

| Threat | Required mitigation and residual boundary |
| --- | --- |
| Malicious client impersonates another user or races first creation | Validate gateway/assertions on every RPC; derive keys from validated claims; atomically reserve the binding; reject conflicting credentials; check all operation ownership. An authenticated arbitrary SQL client still needs filesystem/UDF/resource restrictions. |
| Token theft through diagnostics or errors | Secret wrapper with unconditional redacted Debug/Display/serialization; mark Authorization and Original-Authorization sensitive; sanitize inbound/outbound headers, resolver errors, REST error bodies, traces and panic paths. Never put tokens in Spark conf, SQL SET, GetAll, SET listings, plans, system tables, metrics, exceptions or audit payloads. Client-controlled regex must not turn off protection. Test TRACE too, including signing paths. Do not promise heap erasure for unavoidable library copies. |
| Cross-session result, metadata or credential leakage | Private cache/runtime/provider scope, incarnation keys, checks on every lookup and cursor RPC; expiry/deletion cleanup; no global authorization-dependent caches. Two sessions of the same subject remain separate. |
| Confused deputy / credential exfiltration | Static operator-selected origins, warehouse and audience; scope checks and no credential fallback; validate catalog overrides; reject redirects; no client-controlled filesystem or network credential loaders. Restrict egress and keep gateway bypass impossible. |
| Replay or stolen session IDs | TLS and authenticated gateway-to-backend channel; short-lived audience-restricted assertions and tokens; session/principal/incarnation binding and expiry on every RPC. Bearer tokens remain replayable if stolen: IDs are not a substitute for proof of possession. Optional gateway binding to a session ID reduces assertion replay across sessions; full token replay resistance needs a separate protocol. |
| Revocation, partial failure and overload | Bounded lifetimes, catalog 401/403 enforcement, deadline cancellation, session/credential size/count quotas, bounded resolver timeouts and waiter counts; no automatic mutation replay. State the cancellation and cached-data revocation limits. |

Sail must never trust a client-selected file/URL, accept unsigned identity headers
from an arbitrary backend peer, overwrite a live binding, expose a token through
configuration introspection, or retry an authorization failure as the service
identity. A catalog-only feature must never be advertised as a general multi-tenant
security boundary. Audit only validated subject/tenant, server session ID,
catalog, operation and outcome under operator retention policy; never the token.

## Test plan and incremental implementation

These are proposed upstream tests, not tests run by this documentation change.

1. **Foundation PR:** typed authenticated identity and immutable secret credentials;
   default-off schema and startup validation; documented gateway trust contract.
   Unit-test issuer/audience/expiry checks, duplicate metadata, malformed tokens,
   limits, rejected client paths/URLs, conflicting auth modes and secret formatting.
   Keep existing static/file/Basic/SigV4 behavior unchanged with the feature off.
2. **Session PR:** extract identity before discarding the tonic request; pass it
   through the actor/factory; reserve creation atomically and enforce all-RPC
   ownership. Barrier-test simultaneous first requests with matching/conflicting
   bindings, slow/failed resolver, delete/expiry during creation and waiter cleanup.
   Verify that impersonated protobuf user IDs and guessed operation/session IDs
   cannot release, interrupt, fetch artifacts or reattach another user's session.
3. **Catalog/cache PR:** inject immutable credentials into statically configured
   providers; reject unsafe global caches and isolate runtime/storage state.
   With two users granted different namespaces/tables, warm A's catalog/file
   caches, then prove B cannot list/read/reuse A's metadata, credentials or results.
   Repeat for the same subject with two sessions and for reused client IDs after
   deletion. Assert outbound auth on bootstrap and every REST request, including
   multi-request operations and bounded 401 retries; verify no service fallback.
4. **Lifecycle and integration PR:** fake-clock expiry tests plus concurrent
   queries held at REST barriers throughout a session. Attempt Config/SET/token
   changes while queries run: every outbound call must see the original token
   until cancellation, never a partial catalog. Test reconnect and reattach
   before/after expiry, new-session renewal, retained result cleanup and unknown
   commit outcomes without replay. Capture all logs/traces/conf/system listings
   with sentinel secrets, including Basic/SigV4 diagnostics and REST errors;
   assert absence of raw, encoded and header forms. Test redirect and override
   exfiltration, gateway bypass and token-exchange failure if implemented.

Run existing Sail Rust and Spark Connect regression checks on each relevant PR;
prove default-off wire/configuration compatibility and unchanged static credential
rotation. Add end-to-end Rauthy → gateway → Sail → Lakekeeper authorization/audit
and SeaweedFS storage-boundary tests before operational claims. Benchmark shared
sessions against per-client servers using S5, including concurrency, cancellation,
RSS, startup and TLS/bootstrap overhead. Do not use #2929's debug timing as S5 data.

## Questions for maintainers

- Is immutable identity on a static catalog acceptable feedback on #2929, or
  should the project keep per-client processes as the sole architecture?
- Should the first seam be for embedders only, or a supported gateway assertion
  adapter in the shipped binary? Which trust contract fits Sail's scope?
- Is new-session-only renewal acceptable, including loss of temporary state and
  cancellation at expiry? Which public error code should clients receive?
- Are local-only execution and refusal of global caches reasonable initial limits?
  Which object-store/worker paths require review before expanding the scope?
- Should assertions identify one catalog explicitly or map to an operator-defined
  set? How should audit subjects be represented without trusting Spark user IDs?
- Should token exchange remain the deployment's responsibility? What S5 result
  would justify this complexity relative to the recommended process model?

## Draft Discussion text for owner submission

Suggested title: **User feedback: immutable session identity for static Iceberg REST catalogs**

```draft
Thank you for the guidance in #2929. We understand the concern that partial catalog configuration changes can disrupt concurrent queries in one session and make behavior confusing. We are sharing the user feedback you requested, while keeping catalog configuration static.

Our governed lakehouse uses an authorization gateway, Rauthy OpenID tokens, Lakekeeper per-user catalog permissions and SeaweedFS S3. One fixed catalog credential means Lakekeeper sees one identity for all applications on a shared Sail server. We are evaluating your recommended lightweight per-client servers; our S5 cost measurements are still pending.

Would you consider an explicitly enabled, default-off credential binding made once when a session is created? Catalog endpoint, warehouse and other settings would remain server-owned and static. The session would receive one immutable CatalogCredentials from authenticated gateway metadata, with ownership checks on every RPC, private caches, unconditional secret redaction, no client-selected files/URLs and renewal only through a new session. This would not make arbitrary SQL clients safe tenants or replace storage authorization.

We have a source-based design and test outline covering first-request races, concurrent queries, expiry, session isolation and compatibility. If this direction fits Sail, we would be happy to implement it in small PRs after agreeing on the trust boundary. If per-client servers remain the preferred solution, that feedback will guide our deployment.
```

## Verification limits

Source and #2929 were read live; the API main SHA matched the clone at research
time. No Sail build or authorization prototype was run, and no upstream issue,
PR or message was sent. S5 results, the authenticated gateway contract, token
exchange compatibility, storage credential isolation and distributed execution
remain unverified. Historical [Phase A](../TLS.md) and
[stream evaluations](../evals/2026-11-13-sail-stream-reset.md) remain separate
transport evidence, not security qualification of this design.

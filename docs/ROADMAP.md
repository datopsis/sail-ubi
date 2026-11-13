# Ordered roadmap

**Phase A dispatch item 6:** qualify the unchanged Sail 0.7.3 binary behind the
approved NGINX profile and prove custom-root REST/S3 support on native amd64 and
arm64. [TLS.md](TLS.md) records the exact assertions, current evidence status and
upstream blockers. This is bounded transport qualification, not completion of the
cross-service Phase A integration. The loopback plaintext exception is explicit;
client authentication remains Phase B. Keep credential mode and engine pins fixed.
Custom-root REST/S3 is proven on both architectures. Admission is blocked by the
long-result reset through the pinned proxy. The
[reset investigation](evals/2026-11-13-sail-stream-reset.md) retains the native
transport evidence and controls. The
[fix-options evaluation](evals/2026-11-13-sail-stream-fix-options.md) proves bounded
client reattachment; accepting that recovery contract remains an owner decision.
Resolve that interaction in a separately
reviewed owning-repository change and rerun the unchanged assertion before admission.

1. **First working increment (this PR):** attested Sail wheel acquisition,
   pinned UBI 9.8 and signed RPM closure on amd64/arm64, restricted Spark Connect
   role, fail-closed remote-bind/configuration guards, native runtime evidence,
   real query and local Parquet tests, SBOM and blocking Trivy/Grype gates,
   read-only lock proposals. A failing check remains a blocker, not a waiver.
2. **SCAP evidence:** agree a bounded UBI 9 filesystem rule selection, document
   inapplicable host/orchestrator controls, pin content/scanner inputs, retain
   per-architecture evidence and rationale. No certification inference.
3. **Release signing/publishing:** owner configures reviewed branch protections
   and release trust policy; then add immutable multi-architecture publication,
   signatures, provenance and SBOM attestations, verification, retention and
   rollback. This increment has no publishing workflow or release admission gate.
4. **Deeper qualification:** compile-level Rust dependency/license evidence,
   reproducibility, full linkage and filesystem auditing, authenticated TLS
   gateway rehearsal, authorization/isolation review, malicious-client and
   resource-exhaustion testing, spill/memory limits, long-running workloads,
   storage/catalog integrations, durable-data lifecycle, native Podman and
   orchestrator-specific qualification. Qualify UDFs separately before support.

The container-hardening criteria are a draft reference read during design.
This repository takes no pinned-commit dependency, conformance workflow call or
release-eligible gate from that repository. No human sign-off is supplied here.

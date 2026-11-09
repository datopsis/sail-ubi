# Ordered roadmap

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

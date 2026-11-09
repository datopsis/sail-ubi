# Repository guidance

This repository builds a security-oriented LakeSail Sail Spark Connect server
on Red Hat UBI 9 Micro. Preserve these non-negotiable properties:

- The final image is based on a digest-pinned UBI 9 image and contains no
  package manager, including Python pip/ensurepip bootstrap wheels.
- Sail starts and stays non-root. The entrypoint never changes privileges.
  Default listeners use unprivileged ports.
- Read-only root works with only explicitly declared writable paths, all
  capabilities dropped, and no-new-privileges. Configuration is read-only.
- Every build input is pinned and verified: base manifest-list digests,
  architecture-specific RPM NEVRA + SHA-256, and upstream artifact digests.
  Verify Red Hat RPM signatures against pinned key fingerprints and Sail's
  PyPI Sigstore attestations against its exact release identity and issuer.
  State plainly when an input has only digest verification.
- Spark Connect is the sole supported role. Never pass arbitrary commands
  through the entrypoint or silently enable workers, clusters, Flight or MCP.
- Spark Connect has no built-in authentication to rely on. Default to loopback;
  remote binding fails closed without the documented explicit opt-out.
  The deployment owns authentication, TLS, authorization and network isolation.
- No credentials, private keys or default passwords in images or examples.
- Fixed High/Critical vulnerabilities fail CI with both Trivy and Grype on
  both architectures. Unfixed findings remain in the complete reports.
  Never weaken a gate or hide findings to obtain a green build.
- No FIPS, STIG, OpenShift, Kubernetes or platform support claims without
  corresponding qualification evidence. Native Docker CI is a bounded test.
- No release publishing/signing workflow in this increment. Tags publish nothing.

Follow README build/test commands, docs/ROADMAP.md and docs/VERSION.md.
Keep .in inputs and hash-pinned complete transitive CI requirements together.
Lock update workflows only propose files/diffs for review, with contents: read;
never commit, open PRs or invent human approval records. The container-hardening
standard is a draft reference, not a dependency or release admission gate.

Use Conventional Commit subjects. Never force-push or add AI, assistant,
tool-attribution or Co-Authored-By trailers. Do not modify repository/org settings,
secrets, branch protection or permissions. Do not merge the implementation PR.
Generated bundles, scanner caches and evidence belong outside Git.

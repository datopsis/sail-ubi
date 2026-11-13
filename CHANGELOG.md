# Changelog

## Unreleased

- Gate fixed High/Critical RPM findings on availability of the vendor fix in
  the same UBI repositories used by lock resolution, per architecture. Retain
  deferred findings and vendor versions in complete evidence and job summaries;
  query uncertainty and fixed non-RPM findings still block.
- Recheck native images every six hours and track availability changes in one
  issue, with comments when admission state changes. Preserve hardening,
  publisher checks and provenance labels.
- Finish the stalled RPM refresh after UBI publication: upgrade libuuid from
  2.37.4-25.el9 to 2.37.4-28.el9_9.1 and regenerate the full signed RPM closure
  for both architectures. Keep Sail and base image pins unchanged.

- Permit only the exact upstream `SAIL_CATALOG__LIST` override; test REST catalog
  registration with environment-supplied S3 secrets under the existing hardening.
- Document pinned 0.7.3 Iceberg capabilities, static S3 configuration, and the
  unreleased access-delegation fix needed for the Lakekeeper integration.

- Add a rootless Sail 0.7.3 Spark Connect runtime on pinned UBI 9.8 Micro.
- Verify PyPI Sigstore attestations, Red Hat RPM signatures and locked inputs
  separately for amd64 and arm64; assemble without network package resolution.
- Enforce local Spark Connect role, loopback defaults, explicit remote-bind
  acknowledgement, read-only root and declared writable paths.
- Add real client SQL/Parquet tests, native CI, SBOM and blocking vulnerability
  gates with complete reports, and read-only lock-refresh proposals.
- Document remaining SCAP, publication and deeper qualification work.

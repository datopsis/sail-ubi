# Changelog

## Unreleased

- Add a rootless Sail 0.7.3 Spark Connect runtime on pinned UBI 9.8 Micro.
- Verify PyPI Sigstore attestations, Red Hat RPM signatures and locked inputs
  separately for amd64 and arm64; assemble without network package resolution.
- Enforce local Spark Connect role, loopback defaults, explicit remote-bind
  acknowledgement, read-only root and declared writable paths.
- Add real client SQL/Parquet tests, native CI, SBOM and blocking vulnerability
  gates with complete reports, and read-only lock-refresh proposals.
- Document remaining SCAP, publication and deeper qualification work.

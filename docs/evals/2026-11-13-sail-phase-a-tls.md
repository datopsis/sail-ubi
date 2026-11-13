# Sail Phase A transport evaluation — 2026-11-13

Evaluated the shipped Sail 0.7.3 wheels with pinned pyspark-client 4.2.0 and
datopsis/nginx-ubi `9ef9e822c6b5e508cebef2adff3bb647a206773c`. The native
[amd64 and arm64 run](https://github.com/datopsis/sail-ubi/actions/runs/43374005262)
executed harness commit `3cb9d0c`; actual job logs and both retained evidence
artifacts were inspected. [TLS.md](../TLS.md) contains the full assertion matrix,
deployment configuration, blocker and qualification boundaries.

- **Confirmed:** `SSL_CERT_FILE` loads the per-run custom root for both the real
  REST catalog and S3 clients on both architectures. Each path passed its valid
  operation, six certificate/trust negatives and six restored-valid controls.
  The S3 endpoint verified the actual static SigV4 signature and exact data rows.
- **Confirmed:** verified TLS Connect queries, wrong root/issuer/SAN/expiry and
  plaintext rejection, loopback-only Sail, peer backend refusal and secret
  separation. Existing hardening, publisher and both scanner gates passed.
- **Contradicted:** the assumption that the approved proxy sustains the required
  paced result. Both architectures returned gRPC RST_STREAM error code 2 after
  about 80 seconds, before delivering all 1,000,000 SHA-512 payload rows.
  Direct loopback controls completed with exact results on both architectures.
- **Unresolved:** the precise cause of the proxy/backpressure interaction.
  Sail's HTTP/2 keepalive timing is a hypothesis; no upstream/proxy fix or
  production deployment is qualified here. CA injection is not the blocker.

Each architecture recorded 33 PASS entries and one FAIL entry. The stream remains
blocking; no waiver, verification bypass, credential-mode change, engine upgrade
or proxy-profile modification was introduced. Ephemeral private keys and raw
generated bundles stay outside Git. CI retains sanitized evidence for 14 days.

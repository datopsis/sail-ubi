# Security policy

No supported release is published yet. Report suspected vulnerabilities through
[GitHub private vulnerability reporting](https://github.com/datopsis/sail-ubi/security/advisories/new)
if the owner has enabled it; otherwise ask the owner for a private channel
without disclosing exploit details publicly. This PR does not enable settings.

Spark Connect is unauthenticated. Loopback is the safe image default. Remote
access requires explicit opt-out plus deployment-managed authentication, TLS,
authorization, isolation and resource limits. Never expose it directly to an
untrusted network. Never store credentials or keys in the image or examples.

Fixed High/Critical findings from either Trivy or Grype block CI on each
architecture; no-fix findings are retained in full reports, not suppressed.
Scanner errors also fail. No vulnerability ignore file or report-only gate is
provided. Review the JSON evidence, database timestamps and conservative Cargo
inventory before interpreting a green job as a security claim.

Planned remediation targets after a supported release: fixed Critical/CISA KEV
within 7 days, High within 14 days, other fixes within 30 days. These targets do
not bypass gates or constitute a support commitment for this development image.
There is no FIPS validation, STIG certification or broad platform-support claim.

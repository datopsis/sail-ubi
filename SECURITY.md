# Security policy

No supported release is published yet. Report suspected vulnerabilities through
[GitHub private vulnerability reporting](https://github.com/datopsis/sail-ubi/security/advisories/new)
if the owner has enabled it; otherwise ask the owner for a private channel
without disclosing exploit details publicly. This PR does not enable settings.

Spark Connect is unauthenticated. Loopback is the safe image default. Binding
outside loopback requires explicit opt-out. Deployments own authentication, TLS,
authorization, isolation and resource limits. Never expose Sail directly to an
untrusted network. Never store credentials or keys in the image or examples.

The owner-approved [Phase A TLS design](docs/TLS.md) keeps Sail on
`127.0.0.1:50052` behind the pinned NGINX profile on TLS HTTP/2 port 50051 in the
same network namespace. The sole plaintext exception is this loopback hop;
plaintext across a container bridge is outside that design. Phase A covers
encryption and server identity only; client authentication is Phase B. Keep
clients trusted and isolated while that authentication gap remains. Proxy keys,
Sail credentials and the CA signing key have separate ownership/mount boundaries.
Custom-root support passed both real outbound client paths on both native
architectures. **Slow consumers of large results through the proxy are affected
by a known stream reset near 80 seconds.** The owner's 2026-11-13 decision is
document + retry + upstream: use the narrowly matched
[copy-paste client policy](docs/TLS.md#recommended-client-policy), and require
both the exact-failure canary and complete cursor recovery in native CI. The
policy does not bypass TLS verification, enable general INTERNAL retries, or
prevent the underlying reset. Repeated drops, server restart/session loss,
retention expiry/exhaustion and mutating SQL remain untested. No write
exactly-once guarantee is claimed. See [TLS.md](docs/TLS.md) for the precise
contract and the [unfiled upstream draft](docs/known-issues/sail-keepalive.md).
No engine upgrade, proxy change or certificate-verification bypass is authorized.

High/Critical findings from either Trivy or Grype block CI on each architecture
when a fix is installable from the UBI repositories used to resolve this image's
RPM inputs. The owner defined this rule on 2026-11-12. For an identified Red Hat
RPM with a vendor fixed version, the gate queries fresh metadata using the same
committed `artifacts/ubi.repo` configuration as `scripts/resolve-rpms.py`, isolated
from host repositories and installed packages. An available package of the same
name for the target architecture (or noarch), with RPM epoch/version/release
greater than or equal to any vendor fixed version, blocks. This is a DNF
repository-availability check, not a container upgrade or a dependency-transaction
test. Current image and RPM pins remain the build inputs.

Only a successful query showing no qualifying version defers a fixed RPM finding.
The finding remains in both complete scanner reports, `vulnerabilities.json`,
and the job summary with the vendor fixed version and reason. Deferral does not
mean remediation or absence of risk. Query errors, a 180-second query timeout,
missing/empty repositories, unparsable versions, missing package identity or
architecture, and fixed non-RPM findings still block. A scanner that reports a
fix without its version also blocks. No CVE/package/date exemption list exists.
No-fix findings remain reported as unfixed; the gate never invents a vendor fix.
Scanner errors also fail. Review the JSON evidence, database timestamps and
conservative Cargo inventory before interpreting a green job as a security claim.

Native CI runs on both architectures every six hours and on manual main-branch
runs. It creates or updates one **UBI repository fix availability** issue when
there are deferred/blocking findings or missing evidence, comments when the
state changes, closes it when clear, and reopens the same issue if needed.
Once UBI publishes a qualifying RPM, the next successful query blocks without
changing this rule or the locks. Only the tracking job on scheduled/manual main
runs has `issues: write`; PR jobs and lock proposals remain read-only. The schedule
starts after merge to main and can be delayed by GitHub. Issue watchers receive
GitHub notifications according to their notification settings; no delivery or
immediate publication-detection guarantee is implied.

Planned remediation targets after a supported release: fixed Critical/CISA KEV
within 7 days, High within 14 days, other fixes within 30 days. These targets do
not bypass gates or constitute a support commitment for this development image.
There is no FIPS validation, STIG certification or broad platform-support claim.

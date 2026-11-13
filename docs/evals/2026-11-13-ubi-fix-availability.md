# UBI repository admission validation

The owner decision defines an RPM fix as actionable when the configured UBI repositories advertise a package at or above the vendor fixed EVR. Queries use DNF and comparisons use librpm; they do not execute a package installation. The committed repository configuration is shared with lock resolution, and lint checks every locked RPM URL against it.

Assumptions checked against [DNF repository loading](https://dnf.readthedocs.io/en/latest/api_base.html), [DNF queries](https://dnf.readthedocs.io/en/latest/api_queries.html), and [RPM version comparison](https://rpm.org/docs/6.0.x/man/rpm-version.7): use an empty install root, exclude host repos, require both repos to load, query target-architecture/noarch binaries, compare epoch/version/release with librpm, and defer only a successful negative result. Trivy and Grype retained JSON records were inspected for RPM PURLs, package architecture, vendor fix fields, and non-RPM type distinctions.

## Live queries

On 2026-11-13, ran 22 requests through the production DNF helper against fresh public UBI metadata: ten existing lock versions plus the previously unavailable vendor fix on each architecture. All 22 were available. No query errors occurred.

Package | Requested minimum EVR | amd64 candidate | arm64 candidate
--- | --- | --- | ---
alternatives | 0:1.24-2.el9 | 0:1.24-2.el9 | 0:1.24-2.el9
basesystem | 0:11-13.el9 | 0:11-13.el9 | 0:11-13.el9
bash | 0:5.1.8-9.el9 | 0:5.1.8-9.el9 | 0:5.1.8-9.el9
bzip2-libs | 0:1.0.8-11.el9 | 0:1.0.8-11.el9 | 0:1.0.8-11.el9
ca-certificates | 0:2026.2.92_v9.0.319-90.3.el9_8 | 0:2026.2.92_v9.0.319-90.3.el9_8 | 0:2026.2.92_v9.0.319-90.3.el9_8
coreutils-single | 0:8.32-41.el9_8.1 | 0:8.32-43.el9 | 0:8.32-43.el9
crypto-policies | 0:20260224-1.gitea0f072.el9_8 | 0:20260714-1.git65b74f7.el9 | 0:20260714-1.git65b74f7.el9
expat | 0:2.5.0-6.el9_8.7 | 0:2.5.0-9.el9_9.4 | 0:2.5.0-9.el9_9.4
filesystem | 0:3.16-5.el9 | 0:3.16-5.el9 | 0:3.16-5.el9
findutils | 1:4.8.0-7.el9 | 1:4.8.0-7.el9 | 1:4.8.0-7.el9
libuuid | 2.37.4-28.el9_9 | 0:2.37.4-28.el9_9.1 | 0:2.37.4-28.el9_9.1

The November 11 investigation found only util-linux-family 2.37.4-25.el9 in UBI repositories, with fixed-package URLs returning 404 on both architectures. That is historical evidence, not the current publication state. On November 13, both repositories advertise **2.37.4-28.el9_9.1**, which satisfies the vendor minimum **2.37.4-28.el9_9**. No CVE, package, or date is special-cased by the gate.

## Retained scanner replay

Replayed the actual reports from [CI run 43032586070](https://github.com/datopsis/sail-ubi/actions/runs/43032586070) through the new gate with live repository queries. On both architectures, Trivy and Grype report CVE-2026-53613 against libuuid with a fixed version; all four decisions are **block**, and both gate processes exit 1. This validates the transition after UBI publication. CVE-2026-53615 has no vendor fix in these retained reports and remains **unfixed**, not falsely deferred.

The requested live demonstration of these two CVEs as deferred is no longer possible with this repository state. Tests cover an unavailable fix and preserve its vendor version in summaries. Real publication must win over an expected test narrative.

## Lock refresh

Regenerated with `/usr/bin/python3 scripts/resolve-rpms.py` and `python scripts/render-lock.py`. Both closures remain 58 RPMs, with 17 versions changed per architecture, including libuuid to 2.37.4-28.el9_9.1. Sail artifacts and digest-pinned base images are unchanged. No prior lock-refresh PR or remote branch existed; this PR completes that stalled work.

## Verification boundaries

Unit tests exercise available/unavailable fixes, query errors/timeouts, malformed EVRs, missing repositories/architecture, non-RPM fixed findings, no-fix reporting, epoch/release ordering, multiple fix branches, and issue creation/update/state-change behavior. The native CI reports are the authority for the rebuilt images; links and final results are recorded in the PR.

The scheduled issue workflow is restricted to scheduled/manual main runs. [GitHub schedules run from the default branch](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule); pre-merge tests do not demonstrate actual scheduling or notification delivery. Issue lifecycle behavior is tested with mocked API calls, and a dry-run rendering uses the actual admission evidence. No GitHub settings, secrets, branch protection, or human approvals were changed. Raw scanner reports and query captures remain outside Git.

# Artifact acquisition and verification

Upstream 0.7.3 corresponds to commit
`ac4690078021cf2a5402dc5c7b38a886f1916c73`. Source and publication facts were
checked on 2026-11-09:

- [PyPI](https://pypi.org/project/pysail/0.7.3/) publishes a dependency-free
  `pysail` wheel for Linux x86_64 (manylinux 2.17) and aarch64 (manylinux 2.24).
  UBI 9's glibc 2.34 meets both ABI floors; native CI must still prove linkage.
- [Release workflow](https://github.com/lakehq/sail/blob/ac4690078021cf2a5402dc5c7b38a886f1916c73/.github/workflows/release.yml)
  publishes the wheels with PyPI attestations. We verify their Sigstore
  certificate chain, transparency evidence, artifact subject digest, issuer
  `https://token.actions.githubusercontent.com` and exact certificate identity
  `https://github.com/lakehq/sail/.github/workflows/release.yml@refs/tags/v0.7.3`.
  This is publisher signature verification, not digest-only acquisition.
- Upstream also provides [container build definitions](https://github.com/lakehq/sail/tree/ac4690078021cf2a5402dc5c7b38a886f1916c73/docker):
  quickstart installs wheels on Debian Python; release builds Rust source on
  Debian Python. We do not inherit those images or their mutable build inputs.
- A source build requires Rust, C/link tooling, protoc, Python, Cargo and its
  dependency closure. The attested wheels give a smaller, verifiable input set
  on both architectures for this increment. We do not claim byte-reproducibility
  of upstream's build or prove its compiled Rust dependency set.

`artifacts/sail.lock.json` pins both UBI 9.8 manifest lists and records their
amd64/arm64 child digests. The latest 9.8 tags were resolved directly from the
Red Hat registry on the observation date. Ordinary builds use only these pins.
OCI transport verifies digests; no independent base-image publisher signature
verification is claimed. RPMs are separately publisher-signature verified.

`artifacts/rpms.lock.json` is the full dependency closure resolved from public
UBI 9 BaseOS/AppStream with weak dependencies disabled. Every RPM records
NEVRA, source RPM, size, URL and SHA-256 for each architecture. Red Hat public
keys come separately from security.access.redhat.com; their hashes and complete
fingerprints are pinned. Acquisition uses a fresh RPM trust database, verifies
key fingerprints and signatures, and rejects unexpected bundle files. The
build repeats digest/NEVRA/source-RPM/signature checks offline. It overlays the
locked closure onto UBI Micro while retaining the RPM inventory for scanners.
The required Python pip-wheel bootstrap RPM is removed after installation,
together with ensurepip; runtime package installation is deliberately unavailable.

The source `Cargo.lock` and Apache license are acquired at the release commit
and hash verified. These source files do not have a separately verified publisher
signature. Cargo.lock is included for conservative vulnerability visibility:
optional/build-only crates may appear although they are not in the wheel.
Never label that inventory as a binary-derived SBOM. Findings are not waived
merely because the dependency graph is conservative. Exact dependency and
license attribution for compiled code remains deeper qualification work.

All runtime wheel content, including dist-info license material, is retained.
No detached GPG wheel signature is claimed; verification uses the available
PyPI Sigstore attestations. Trust-root updates and vulnerability databases are
necessarily live security data, distinct from pinned build inputs.

## Regeneration

With the documented hash-pinned CI environment, GitHub CLI authenticated for
read access, RPM/GnuPG and system Python DNF bindings:

```sh
python scripts/update-upstream.py --version 0.7.3
/usr/bin/python3 scripts/resolve-rpms.py
python scripts/render-lock.py
python scripts/update-tools.py
bash scripts/update-python-locks.sh
python scripts/fetch.py --arch amd64
python scripts/fetch.py --arch arm64
python scripts/lint.py
```

Delete stale `.artifact-bundle` files before acquiring a different lock; extra
or changed files fail admission intentionally. RPM resolution never executes
foreign-architecture code. Refreshing locks is a review activity, not a build
step. Scanner archives are pinned by SHA-256 and version; no scanner archive
publisher-signature verification is claimed. Python tool inputs and complete
transitive hashes live alongside one another in `.github/requirements/`.
Keep Python 3.11 for regeneration, matching CI. The source-only Spark client is
installed with locked setuptools/wheel and without isolated build dependency
resolution. No client package enters the runtime image.

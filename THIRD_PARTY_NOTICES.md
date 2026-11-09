# Third-party notices

Repository packaging is Apache-2.0 (LICENSE). LakeSail Sail 0.7.3 is Apache-2.0;
its unmodified upstream license and wheel dist-info license material are retained
inside the image. The pinned release has no top-level NOTICE file.

Red Hat UBI and RPM packages retain their own license/redistribution terms,
including applicable source-offer obligations. RPM license material is preserved.
UBI branding is not a Datopsis endorsement or certification. The image license
label identifies this project's and Sail's primary license; it is not a claim
that every included package is Apache-2.0.

Bundled Rust/Python/native dependencies have their own licenses. Cargo.lock is
a source-declared inventory, not proof of compiled contents or a complete legal
bill of materials. Complete compiled-dependency/license attribution and release
redistribution review remain roadmap work before publishing. No incompatible
Sail license term was identified for this development increment.

Build-tooling patterns were adapted from the Apache-2.0 datopsis UBI sibling
repositories named in the implementation PR. No code or pinned dependency from
the draft container-hardening standard is imported.

# Version rules

This increment is identified by its Git commit and pull request. It creates no
version tag, source-only release or published image. Upstream Sail 0.7.3 is an
input version, not a Datopsis release identifier. Changes accumulate under
`Unreleased` in CHANGELOG.md.

Future container releases should follow the sibling format:
`v<sail-version>-ubi<major>-r<YYYYMMDD>.<daily-sequence>`. Dates use UTC and daily
sequences start at 1. Tags and image digests are immutable; never reuse, move or
force-push them. Repository-only documentation/test/tool changes need no tag.
Image-affecting changes require a new release when publishing is introduced.

Before that future work, define and test release identity, owner review,
signing, provenance, vulnerability admission and immutable publication. No
workflow in this increment runs on tags or has publication permissions.

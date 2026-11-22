# ADR-009: Event evolution (synthetic)

Status: accepted

- Additive, optional fields stay on the existing `.v1` topic with a minor
  platform-contracts release.
- Removing/renaming fields or changing meaning requires a `.v2` topic with a
  dual-publish period.
- Consumers should be tolerant readers. Known exception: `search-indexer`
  validates strictly against a vendored schema; it must be updated before any
  producer adds fields to `metadata.dataset.changed.v1`.

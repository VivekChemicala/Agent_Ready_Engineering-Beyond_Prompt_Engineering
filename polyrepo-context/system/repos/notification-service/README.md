# notification-service

Emails dataset owners when a transformation run scores below threshold.
Synthetic example service.

Owner: team-platform

- Consumes `transformation.result.published.v1` (uses `dataset_urn` and `score`).
- Looks up the owner with `MetadataClient.get_dataset(urn).owner`.

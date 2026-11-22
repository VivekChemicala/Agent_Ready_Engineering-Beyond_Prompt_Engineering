# notification-service

Emails dataset owners when a data-quality run scores below threshold.
Synthetic example service.

Owner: team-platform

- Consumes `dq.result.published.v1` (uses `dataset_urn` and `score`).
- Looks up the owner with `MetadataClient.get_dataset(urn).owner`.

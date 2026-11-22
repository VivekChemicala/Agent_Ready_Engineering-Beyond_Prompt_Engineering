# usage-metering

Aggregates query access logs per principal and dataset for chargeback.
Synthetic example service.

Owner: team-platform

- Consumes `gateway.access.logged.v1` (`principal`, `dataset_urn`, `row_count`).

# entitlements-service

Owns access policies and grants and answers access decisions for the platform.
Synthetic example service written for an experiment.

Owner: team-access

- `POST /v1/access/decide` -> `{allow, reason, policy_id}` for (principal, dataset, action).
- Grants look like `domain:<domain>:read`, `dataset:<urn>:read`.
- Dataset attributes (domain, owner) are fetched with `platform_sdk.MetadataClient`
  and cached; the cache is invalidated by `metadata.dataset.changed.v1`.
- Decisions only. Enforcement happens in the caller.

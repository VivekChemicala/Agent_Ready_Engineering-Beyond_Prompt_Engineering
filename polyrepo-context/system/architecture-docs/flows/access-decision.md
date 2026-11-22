# Flow: access decision (synthetic)

1. A consumer calls `query-gateway` `POST /v1/query`.
2. `query-gateway` calls `entitlements-service` `POST /v1/access/decide`
   through `platform_sdk.EntitlementsClient`.
3. `entitlements-service` loads dataset attributes from `metadata-graph`
   (`GET /v1/datasets/{urn}`) through `platform_sdk.MetadataClient`, cached and
   invalidated by `metadata.dataset.changed.v1`, then evaluates grants.
4. The decision is returned to `query-gateway`, which enforces it: rejects the
   request or runs the query and shapes the result (see ADR-007).
5. `query-gateway` emits `gateway.access.logged.v1`.

Today decisions are dataset-level only (`allow` / `reason` / `policy_id`).

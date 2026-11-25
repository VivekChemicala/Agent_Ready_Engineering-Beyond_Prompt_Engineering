# consumption-gateway

Public query endpoint for data consumers (BI tools, notebooks, apps).
Synthetic example service written for an experiment.

Owner: team-consumption

Flow for `POST /v1/query`:
1. Ask entitlements for a decision (`platform_sdk.EntitlementsClient.decide`).
2. If allowed, run the query against the warehouse and return rows.
3. Emit `consumption.access.logged.v1`.

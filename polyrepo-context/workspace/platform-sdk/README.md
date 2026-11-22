# platform-sdk

Shared Python SDK for platform services. Synthetic example library.

Owner: team-platform. Current release: 3.4.1 (bundles platform-contracts 2.3.0).

- `MetadataClient` - typed client for the metadata-graph REST API.
- `EntitlementsClient` - typed client for entitlements-service decisions.
- `events` - publish/subscribe helpers; payloads are validated against the
  bundled platform-contracts schemas before publish.

Models are explicit dataclasses: fields not declared on a model are dropped
when responses are parsed.

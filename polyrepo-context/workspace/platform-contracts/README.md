# platform-contracts

Source of truth for event schemas (JSON Schema) and REST APIs (OpenAPI).
Synthetic example repository. Owner: team-platform. Current release: 2.3.0.

- `events/<topic>.json` - one schema per topic.
- `openapi/<service>.yaml` - one spec per service API.

Versioning: semver. Additive optional fields = minor release; removing or
renaming fields = new topic version (`.v2`) / new API version (`/v2`).
Released as a Python package consumed by platform-sdk.

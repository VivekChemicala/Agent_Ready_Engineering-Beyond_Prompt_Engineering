# platform-catalog

Service catalog for the data platform (Backstage-style).
Synthetic example repository written for an experiment.

- `components/` - one entity per repository: owner team, lifecycle, APIs
  provided/consumed, library dependencies, events produced/consumed.
- `apis/` - one entity per REST API with provider and consumers.
- `topics.yaml` - every event topic with producer and consumers.
- `dependency-graph.json` / `.md` - generated graph of all of the above.

Each component is a separate git repository named after the component
(`example-org/<name>`). Teams update their entity in the same PR that
changes an integration.

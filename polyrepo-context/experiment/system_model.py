"""Single source of truth for the SYNTHETIC polyrepo system used in experiment 3.

Every service, team, topic and endpoint here is fictional. The catalog files
(arms B/C) and the full dependency graph used for scoring are generated from
this model so they cannot drift apart.
"""

from __future__ import annotations

EVENTS = {
    "ingestion.schema.discovered.v1": "ingestion-service",
    "ingestion.batch.landed.v1": "ingestion-service",
    "ingestion.job.completed.v1": "ingestion-service",
    "metadata.dataset.changed.v1": "metadata-graph",
    "dq.result.published.v1": "dq-engine",
    "gateway.access.logged.v1": "query-gateway",
}

APIS = {
    "metadata-graph-api": {
        "owner": "metadata-graph",
        "endpoints": ["GET /v1/datasets/{urn}", "GET /v1/datasets/{urn}/columns",
                      "PUT /v1/datasets/{urn}/owner"],
    },
    "entitlements-api": {
        "owner": "entitlements-service",
        "endpoints": ["POST /v1/access/decide",
                      "GET /v1/principals/{principal_id}/grants"],
    },
    "query-api": {"owner": "query-gateway", "endpoints": ["POST /v1/query"]},
    "dq-api": {"owner": "dq-engine",
               "endpoints": ["GET /v1/rules", "POST /v1/rules"]},
}

COMPONENTS = {
    "ingestion-service": dict(
        type="service", owner="team-ingest", lifecycle="production",
        description="Source connectors; discovers source schemas and lands batches.",
        produces=["ingestion.schema.discovered.v1", "ingestion.batch.landed.v1",
                  "ingestion.job.completed.v1"],
        consumes=[], provides_apis=[], consumes_apis=[],
        depends_on=["platform-sdk"]),
    "metadata-graph": dict(
        type="service", owner="team-graph", lifecycle="production",
        description="Context graph of datasets, columns, owners and quality scores.",
        produces=["metadata.dataset.changed.v1"],
        consumes=["ingestion.schema.discovered.v1", "dq.result.published.v1"],
        provides_apis=["metadata-graph-api"], consumes_apis=[],
        depends_on=["platform-sdk"]),
    "entitlements-service": dict(
        type="service", owner="team-access", lifecycle="production",
        description="Access policies and grants; answers access decisions.",
        produces=[], consumes=["metadata.dataset.changed.v1"],
        provides_apis=["entitlements-api"], consumes_apis=["metadata-graph-api"],
        depends_on=["platform-sdk"]),
    "query-gateway": dict(
        type="service", owner="team-serving", lifecycle="production",
        description="Serves query results to data consumers.",
        produces=["gateway.access.logged.v1"], consumes=[],
        provides_apis=["query-api"], consumes_apis=["entitlements-api"],
        depends_on=["platform-sdk"]),
    "dq-engine": dict(
        type="service", owner="team-quality", lifecycle="production",
        description="Runs data-quality rules on landed batches.",
        produces=["dq.result.published.v1"], consumes=["ingestion.batch.landed.v1"],
        provides_apis=["dq-api"], consumes_apis=["metadata-graph-api"],
        depends_on=["platform-sdk"]),
    "search-indexer": dict(
        type="service", owner="team-discovery", lifecycle="production",
        description="Indexes dataset metadata for catalog search.",
        produces=[], consumes=["metadata.dataset.changed.v1"],
        provides_apis=[], consumes_apis=[],
        depends_on=["platform-contracts"]),
    "lineage-service": dict(
        type="service", owner="team-discovery", lifecycle="production",
        description="Builds dataset lineage from ingestion jobs.",
        produces=[], consumes=["ingestion.job.completed.v1",
                               "metadata.dataset.changed.v1"],
        provides_apis=[], consumes_apis=[], depends_on=["platform-sdk"]),
    "notification-service": dict(
        type="service", owner="team-platform", lifecycle="production",
        description="Emails dataset owners about failed quality checks.",
        produces=[], consumes=["dq.result.published.v1"],
        provides_apis=[], consumes_apis=["metadata-graph-api"],
        depends_on=["platform-sdk"]),
    "usage-metering": dict(
        type="service", owner="team-platform", lifecycle="production",
        description="Aggregates query access logs for chargeback.",
        produces=[], consumes=["gateway.access.logged.v1"],
        provides_apis=[], consumes_apis=[], depends_on=[]),
    "reporting-service": dict(
        type="service", owner="team-graph", lifecycle="decommissioned",
        description="Legacy metadata reports. Decommissioned; repository archived.",
        produces=[], consumes=[], provides_apis=[], consumes_apis=[],
        depends_on=[]),
    "platform-sdk": dict(
        type="library", owner="team-platform", lifecycle="production",
        description="Shared Python SDK: typed REST clients and event helpers.",
        produces=[], consumes=[], provides_apis=[],
        consumes_apis=["metadata-graph-api", "entitlements-api"],
        depends_on=["platform-contracts"]),
    "platform-contracts": dict(
        type="library", owner="team-platform", lifecycle="production",
        description="Event JSON Schemas and OpenAPI specs (source of truth).",
        produces=[], consumes=[], provides_apis=[], consumes_apis=[],
        depends_on=[]),
    "platform-e2e": dict(
        type="test-suite", owner="team-platform", lifecycle="production",
        description="Cross-service end-to-end tests run in the integration environment.",
        produces=[], consumes=[], provides_apis=[], consumes_apis=[],
        depends_on=["ingestion-service", "metadata-graph", "entitlements-service",
                    "query-gateway", "dq-engine"]),
}


def edges() -> set[frozenset[str]]:
    """Every direct dependency in the live system, as unordered pairs."""
    out: set[frozenset[str]] = set()
    for name, c in COMPONENTS.items():
        if c["lifecycle"] == "decommissioned":
            continue
        for topic in c["consumes"]:
            out.add(frozenset((name, EVENTS[topic])))
        for api in c["consumes_apis"]:
            out.add(frozenset((name, APIS[api]["owner"])))
        for dep in c["depends_on"]:
            out.add(frozenset((name, dep)))
    return out

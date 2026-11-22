from platform_sdk import events


def register(graph) -> None:
    events.subscribe("ingestion.job.completed.v1",
                     lambda p: graph.add_edge(p["source"], p["target_urn"]))
    events.subscribe("metadata.dataset.changed.v1",
                     lambda p: graph.rename(p["dataset"]["urn"], p["dataset"]["name"]))

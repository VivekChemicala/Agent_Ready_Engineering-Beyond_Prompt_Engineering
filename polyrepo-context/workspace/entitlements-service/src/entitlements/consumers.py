from platform_sdk import events


def register(engine) -> None:
    events.subscribe("metadata.dataset.changed.v1",
                     lambda p: engine.invalidate(p["dataset"]["urn"]))

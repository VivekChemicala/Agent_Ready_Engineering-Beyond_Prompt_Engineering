from platform_sdk import MetadataClient, events

THRESHOLD = 0.9


def on_dq_result(metadata: MetadataClient, mailer, payload: dict) -> None:
    if payload["score"] >= THRESHOLD:
        return
    owner = metadata.get_dataset(payload["dataset_urn"]).owner
    mailer.send(owner, f"DQ score {payload['score']:.2f} for {payload['dataset_urn']}")


def register(metadata, mailer) -> None:
    events.subscribe("dq.result.published.v1",
                     lambda p: on_dq_result(metadata, mailer, p))

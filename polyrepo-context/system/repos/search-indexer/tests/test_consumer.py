from indexer.consumer import handle


class Sink:
    def __init__(self):
        self.items = []

    def upsert(self, k, v):
        self.items.append(k)

    def send(self, topic, v):
        self.items.append(topic)


def test_unknown_field_goes_to_dlq():
    sink = Sink()
    payload = {"event_id": "1", "occurred_at": "t", "change_type": "UPDATED",
               "dataset": {"urn": "u", "name": "n", "domain": "d", "owner": "o",
                           "columns": [], "extra": 1}}
    assert handle(payload, sink, sink) is False

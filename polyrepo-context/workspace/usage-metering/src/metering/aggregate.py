from collections import Counter

TOPIC = "gateway.access.logged.v1"


def aggregate(events_iter) -> Counter:
    totals = Counter()
    for e in events_iter:
        totals[(e["principal"], e["dataset_urn"])] += e["row_count"]
    return totals

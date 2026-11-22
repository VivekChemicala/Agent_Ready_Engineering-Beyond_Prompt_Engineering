from usage_metering.consumer import ColumnMeter


def event(urn, owner, n, **extra):
    cols = [{"name": f"c{i}", "type": "string", "tags": [], **extra} for i in range(n)]
    return {"event_type": "metadata.dataset.changed", "urn": urn, "change": "CREATED", "owner": owner, "columns": cols}


def test_counts_latest_state_per_dataset():
    m = ColumnMeter()
    m.on_dataset_changed(event("u1", "a", 2))
    m.on_dataset_changed(event("u1", "a", 3))
    m.on_dataset_changed(event("u2", "b", 1))
    assert m.columns_by_owner() == {"a": 3, "b": 1}


def test_ignores_unknown_fields():
    m = ColumnMeter()
    m.on_dataset_changed(event("u1", "a", 2, anything="x"))
    assert m.columns_by_owner() == {"a": 2}

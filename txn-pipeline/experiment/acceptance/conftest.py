"""Hidden acceptance suite. TXN_WORKSPACE points at the txn-pipeline project
under test; its src/ is imported fresh for each session."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

WORKSPACE = Path(os.environ["TXN_WORKSPACE"]).resolve()
sys.path.insert(0, str(WORKSPACE / "src"))


def msg(offset, value, key="k", ts=1793836800000):
    return json.dumps({"offset": offset, "key": key, "timestamp": ts,
                       "value": value})


def txn(tid="t-1", **over):
    value = {"transaction_id": tid, "customer_id": "cust-1", "amount": 10.5,
             "currency": "USD", "event_time": "2026-11-01T10:00:00Z",
             "merchant_id": "m-1"}
    over = {"transaction_id": tid, **over}
    for k, v in over.items():
        if v is DROP:
            value.pop(k, None)
        else:
            value[k] = v
    return value


DROP = object()


class Run:
    def __init__(self, tmp: Path, partitions: dict[int | str, list[str]]):
        self.inp = tmp / "in"
        self.out = tmp / "out"
        self.inp.mkdir(parents=True, exist_ok=True)
        for p, lines in partitions.items():
            name = p if isinstance(p, str) else f"partition-{p}.jsonl"
            (self.inp / name).write_text("\n".join(lines) + "\n")

    def go(self):
        from txn_pipeline import run_pipeline
        self.returned = run_pipeline(self.inp, self.out)
        return self

    def lines(self, name):
        path = self.out / name
        return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

    @property
    def valid(self):
        return self.lines("valid.jsonl")

    @property
    def rejects(self):
        return self.lines("rejects.jsonl")

    @property
    def metrics(self):
        return json.loads((self.out / "metrics.json").read_text())

    def text(self, name):
        return (self.out / name).read_text()


def all_ints(obj):
    """Every integer anywhere in a JSON value."""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, int):
        return [obj]
    if isinstance(obj, dict):
        obj = list(obj.values())
    if isinstance(obj, list):
        return [i for v in obj for i in all_ints(v)]
    return []


def find_values(obj, key):
    """All values stored under `key` anywhere in a JSON object."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                found.append(v)
            found += find_values(v, key)
    elif isinstance(obj, list):
        for v in obj:
            found += find_values(v, key)
    return found


@pytest.fixture
def run(tmp_path):
    def make(partitions):
        return Run(tmp_path, partitions).go()
    return make


@pytest.fixture
def workspace():
    return WORKSPACE

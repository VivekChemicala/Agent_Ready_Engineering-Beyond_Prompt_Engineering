"""Hidden acceptance tests. Neither arm sees this file.

TestRequirements - the six task requirements, judged on accept/reject outcome
                   only (format-agnostic where the task prompt is silent).
TestContract     - exact output/schema contract and documented conventions.
TestRobustness   - bad input never crashes the run; output is deterministic.
"""

from __future__ import annotations

import json
import subprocess
import sys

from conftest import DROP, WORKSPACE, all_ints, find_values, msg, txn

REASONS = ["MALFORMED_EVENT", "NULL_CUSTOMER_ID", "SCHEMA_VIOLATION",
           "INVALID_CURRENCY", "DUPLICATE_TRANSACTION"]
VALID_KEYS = {"transaction_id", "customer_id", "amount", "currency",
              "event_time", "merchant_id", "source_partition", "source_offset"}
REJECT_KEYS = {"source_partition", "source_offset", "reason_code",
               "reason_detail", "raw"}


def valid_ids(r):
    return [find_values(row, "transaction_id")[0] for row in r.valid]


def codes(r):
    return [row["reason_code"] for row in r.rejects]


def mixed_batch():
    return {
        0: [msg(0, txn("a1")),
            msg(1, txn("a2", customer_id=None)),
            msg(2, txn("a3", currency="XYZ")),
            msg(3, txn("a1")),
            msg(4, txn("a4", amount="12.00")),
            "not json at all"],
        1: [msg(0, txn("b1", currency="EUR")),
            "",
            msg(1, txn("b4")),
            msg(2, txn("b2", event_time=DROP)),
            msg(3, txn("b3", currency="JPY", amount=500))],
    }


class TestRequirements:
    def test_r1_schema_violations_rejected(self, run):
        r = run({0: [msg(0, txn("ok")),
                     msg(1, txn("x1", amount=DROP)),
                     msg(2, txn("x2", amount="10.50")),
                     msg(3, txn(DROP)),
                     msg(4, txn("x4", event_time=DROP)),
                     msg(5, txn("x5", merchant_id=DROP)),
                     json.dumps({"offset": 6, "value": "not-an-object"})]})
        assert valid_ids(r) == ["ok"]
        assert len(r.rejects) == 6

    def test_r2_null_customer_rejected(self, run):
        r = run({0: [msg(0, txn("ok")),
                     msg(1, txn("n1", customer_id=None)),
                     msg(2, txn("n2", customer_id=DROP))]})
        assert valid_ids(r) == ["ok"]
        assert len(r.rejects) == 2

    def test_r3_duplicates_rejected_first_kept(self, run):
        r = run({0: [msg(0, txn("d1", amount=1)),
                     msg(1, txn("d1", amount=2)),
                     msg(2, txn("d2"))],
                 1: [msg(0, txn("d1", amount=3))]})
        assert valid_ids(r) == ["d1", "d2"]
        first = [row for row in r.valid if find_values(row, "transaction_id")
                 == ["d1"]][0]
        assert find_values(first, "amount") == [1]
        assert len(r.rejects) == 2

    def test_r4_unapproved_currency_rejected(self, run):
        r = run({0: [msg(0, txn("c1", currency="USD")),
                     msg(1, txn("c2", currency="XYZ")),
                     msg(2, txn("c3", currency="EUR")),
                     msg(3, txn("c4", currency="BTC")),
                     msg(4, txn("c5", currency="JPY", amount=900))]})
        assert valid_ids(r) == ["c1", "c3", "c5"]
        assert len(r.rejects) == 2

    def test_r5_invalid_events_go_to_reject_dataset(self, run):
        r = run(mixed_batch())
        assert sorted(valid_ids(r)) == ["a1", "b1", "b3", "b4"]
        assert len(r.rejects) == 6
        text = r.text("rejects.jsonl")
        for tid in ("a2", "a4", "b2"):
            assert tid in text
        assert "not json at all" in text

    def test_r6_structured_metrics(self, run):
        r = run(mixed_batch())
        m = r.metrics
        assert isinstance(m, dict)
        assert {10, 4, 6} <= set(all_ints(m))
        assert r.returned == m


class TestContract:
    def test_valid_record_shape(self, run):
        r = run({3: [msg(7, txn("v1", channel="web", amount=12))]})
        assert r.valid == [{"transaction_id": "v1", "customer_id": "cust-1",
                            "amount": 12, "currency": "USD",
                            "event_time": "2026-11-01T10:00:00Z",
                            "merchant_id": "m-1", "source_partition": 3,
                            "source_offset": 7}]

    def test_reject_record_shape(self, run):
        line = msg(4, txn("r1", currency="XYZ"))
        r = run({2: [line]})
        [rej] = r.rejects
        assert set(rej) == REJECT_KEYS
        assert rej["source_partition"] == 2
        assert rej["source_offset"] == 4
        assert rej["reason_code"] == "INVALID_CURRENCY"
        assert isinstance(rej["reason_detail"], str) and rej["reason_detail"]
        assert rej["raw"] == line

    def test_reason_codes(self, run):
        r = run({0: ["{broken",
                     msg(1, txn("e1", customer_id=None)),
                     msg(2, txn("e2", amount="5")),
                     msg(3, txn("e3", currency="GBX")),
                     msg(4, txn("ok")),
                     msg(5, txn("ok"))]})
        assert codes(r) == REASONS

    def test_malformed_offset_is_null(self, run):
        r = run({0: ["{broken", json.dumps({"offset": "x", "value": txn()})]})
        assert [x["source_offset"] for x in r.rejects] == [None, None]
        assert codes(r) == ["MALFORMED_EVENT", "MALFORMED_EVENT"]

    def test_blank_customer_is_null_customer(self, run):
        r = run({0: [msg(0, txn("b1", customer_id="")),
                     msg(1, txn("b2", customer_id="   ")),
                     msg(2, txn("b3", customer_id=DROP))]})
        assert codes(r) == ["NULL_CUSTOMER_ID"] * 3

    def test_non_string_customer_is_schema_violation(self, run):
        r = run({0: [msg(0, txn("s1", customer_id=12345))]})
        assert codes(r) == ["SCHEMA_VIOLATION"]

    def test_precedence(self, run):
        r = run({0: [json.dumps({"offset": -1, "value": txn(customer_id=None)}),
                     msg(1, txn("p1", customer_id=None, amount="x",
                                currency="xx")),
                     msg(2, txn("p2", amount=-5, currency="XYZ"))]})
        assert codes(r) == ["MALFORMED_EVENT", "NULL_CUSTOMER_ID",
                            "SCHEMA_VIOLATION"]

    def test_currency_is_case_sensitive(self, run):
        r = run({0: [msg(0, txn("lc", currency="usd"))]})
        assert codes(r) == ["INVALID_CURRENCY"]

    def test_amount_rules(self, run):
        r = run({0: [msg(0, txn("z1", amount=0)),
                     msg(1, txn("z2", amount=-1.5)),
                     msg(2, txn("z3", amount=True)),
                     msg(3, txn("z4", amount=7))]})
        assert codes(r) == ["SCHEMA_VIOLATION"] * 3
        assert valid_ids(r) == ["z4"]

    def test_event_time_rules(self, run):
        r = run({0: [msg(0, txn("t1", event_time="2026-11-01T10:00:00.123Z")),
                     msg(1, txn("t2", event_time="2026-11-01T10:00:00+00:00")),
                     msg(2, txn("t3", event_time="2026-02-30T10:00:00Z")),
                     msg(3, txn("t4", event_time="2026-11-01 10:00:00Z"))]})
        assert valid_ids(r) == ["t1"]
        assert codes(r) == ["SCHEMA_VIOLATION"] * 3

    def test_rejected_event_does_not_reserve_id(self, run):
        r = run({0: [msg(0, txn("dup", currency="XYZ")),
                     msg(1, txn("dup", amount=2)),
                     msg(2, txn("dup", amount=3))]})
        assert [x["amount"] for x in r.valid] == [2]
        assert codes(r) == ["INVALID_CURRENCY", "DUPLICATE_TRANSACTION"]

    def test_numeric_partition_order(self, run):
        r = run({10: [msg(0, txn("n", amount=10))],
                 2: [msg(0, txn("n", amount=2))]})
        assert [(x["source_partition"], x["amount"]) for x in r.valid] == [(2, 2)]
        assert [x["source_partition"] for x in r.rejects] == [10]

    def test_non_partition_files_ignored(self, run):
        r = run({0: [msg(0, txn("a"))],
                 "notes.txt": ["hello"],
                 "partition-x.jsonl": [msg(0, txn("b"))],
                 "partition-1.json": [msg(0, txn("c"))]})
        assert valid_ids(r) == ["a"] and r.rejects == []

    def test_blank_lines_not_counted(self, run):
        r = run({0: ["", msg(0, txn("a")), "   ", ""]})
        assert r.metrics["input_records"] == 1
        assert r.rejects == []

    def test_metrics_exact(self, run):
        r = run(mixed_batch())
        assert r.metrics == {
            "schema_version": "1.0",
            "input_records": 10, "valid_records": 4, "rejected_records": 6,
            "rejects_by_reason": {"MALFORMED_EVENT": 1, "NULL_CUSTOMER_ID": 1,
                                  "SCHEMA_VIOLATION": 2, "INVALID_CURRENCY": 1,
                                  "DUPLICATE_TRANSACTION": 1},
            "partitions": {
                "0": {"input_records": 6, "valid_records": 1,
                      "rejected_records": 5},
                "1": {"input_records": 4, "valid_records": 3,
                      "rejected_records": 1}}}
        assert r.returned == r.metrics

    def test_output_order_is_processing_order(self, run):
        r = run(mixed_batch())
        assert [(x["source_partition"], x["source_offset"]) for x in r.valid] \
            == [(0, 0), (1, 0), (1, 1), (1, 3)]
        assert [(x["source_partition"], x["source_offset"])
                for x in r.rejects] == [(0, 1), (0, 2), (0, 3), (0, 4),
                                        (0, None), (1, 2)]

    def test_currencies_come_from_config(self, tmp_path):
        cfg = WORKSPACE / "config" / "approved_currencies.json"
        inp = tmp_path / "in"
        inp.mkdir()
        (inp / "partition-0.jsonl").write_text(
            msg(0, txn("q1", currency="CHF")) + "\n"
            + msg(1, txn("q2", currency="EUR")) + "\n")
        original = cfg.read_text()
        try:
            cfg.write_text(json.dumps({"approved_currencies": ["USD", "CHF"]}))
            subprocess.run(
                [sys.executable, "-c", "import sys; from txn_pipeline import "
                 "run_pipeline; run_pipeline(sys.argv[1], sys.argv[2])",
                 str(inp), str(tmp_path / "out")],
                cwd=WORKSPACE, env={"PYTHONPATH": str(WORKSPACE / "src"),
                                    "PATH": "/usr/bin:/bin"},
                capture_output=True, text=True, timeout=60, check=True)
        finally:
            cfg.write_text(original)
        out = tmp_path / "out"
        valid = [json.loads(x) for x in (out / "valid.jsonl").read_text().splitlines()
                 if x.strip()]
        assert [v["transaction_id"] for v in valid] == ["q1"]

    def test_cli(self, tmp_path):
        inp = tmp_path / "in"
        inp.mkdir()
        (inp / "partition-0.jsonl").write_text(msg(0, txn("cli")) + "\n")
        env_src = str(WORKSPACE / "src")
        ok = subprocess.run(
            [sys.executable, "-m", "txn_pipeline", "--input", str(inp),
             "--output", str(tmp_path / "out")],
            cwd=tmp_path, env={"PYTHONPATH": env_src, "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=60)
        assert ok.returncode == 0, ok.stderr
        for name in ("valid.jsonl", "rejects.jsonl", "metrics.json"):
            assert (tmp_path / "out" / name).exists()
        bad = subprocess.run(
            [sys.executable, "-m", "txn_pipeline", "--input",
             str(tmp_path / "missing"), "--output", str(tmp_path / "o2")],
            cwd=tmp_path, env={"PYTHONPATH": env_src, "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=60)
        assert bad.returncode != 0

    def test_outputs_overwritten(self, run, tmp_path):
        from txn_pipeline import run_pipeline
        r = run({0: [msg(0, txn("a")), msg(1, txn("b", currency="XYZ"))]})
        (r.inp / "partition-0.jsonl").write_text(msg(0, txn("c")) + "\n")
        run_pipeline(r.inp, r.out)
        assert valid_ids(r) == ["c"] and r.rejects == []


class TestRobustness:
    def test_hostile_lines_never_raise(self, run):
        lines = ["[1, 2, 3]", '"just a string"', "null", "42",
                 json.dumps({"offset": 1, "value": None}),
                 json.dumps({"offset": True, "value": txn("w0")}),
                 json.dumps({"value": txn("w1")}),
                 '{"offset": 2, "value": {"transaction_id": "w2", '
                 '"customer_id": "c", "amount": NaN, "currency": "USD", '
                 '"event_time": "2026-11-01T10:00:00Z", "merchant_id": "m"}}',
                 msg(3, txn("w3", amount=10 ** 400)),
                 msg(4, txn("w4", currency=None)),
                 msg(5, txn("w5", event_time=1793836800)),
                 msg(6, txn(["list-id"])),
                 msg(7, txn("ünïcødé-✓", merchant_id="商户")),
                 "{\"offset\": 8, \"value\": {}}"]
        r = run({0: lines})
        assert len(r.valid) + len(r.rejects) == len(lines)
        assert isinstance(r.metrics, dict)
        ids = valid_ids(r)
        assert "ünïcødé-✓" in ids and set(ids) <= {"w3", "ünïcødé-✓"}

    def test_empty_input(self, run):
        r = run({})
        assert isinstance(r.metrics, dict)
        assert r.valid == [] and r.rejects == []

    def test_nested_output_dir_created(self, tmp_path):
        from txn_pipeline import run_pipeline
        inp = tmp_path / "in"
        inp.mkdir()
        (inp / "partition-0.jsonl").write_text(msg(0, txn()) + "\n")
        run_pipeline(inp, tmp_path / "a" / "b" / "out")
        assert (tmp_path / "a" / "b" / "out" / "metrics.json").exists()

    def test_deterministic(self, tmp_path):
        from txn_pipeline import run_pipeline
        inp = tmp_path / "in"
        inp.mkdir()
        for p, lines in mixed_batch().items():
            (inp / f"partition-{p}.jsonl").write_text("\n".join(lines) + "\n")
        names = ("valid.jsonl", "rejects.jsonl", "metrics.json")
        run_pipeline(inp, tmp_path / "out")
        first = [(tmp_path / "out" / n).read_bytes() for n in names]
        run_pipeline(inp, tmp_path / "out")
        assert [(tmp_path / "out" / n).read_bytes() for n in names] == first

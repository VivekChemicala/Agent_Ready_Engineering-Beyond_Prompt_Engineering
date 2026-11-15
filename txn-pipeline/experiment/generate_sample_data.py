"""Generate the synthetic sample partitions in data/input (deterministic)."""

from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "input"
CURRENCIES = ["USD", "EUR", "GBP", "CAD", "JPY"]


def payload(rng: random.Random, n: int) -> dict:
    return {
        "transaction_id": f"txn-{n:05d}",
        "customer_id": f"cust-{rng.randint(1, 40):04d}",
        "amount": round(rng.uniform(1, 900), 2),
        "currency": rng.choice(CURRENCIES),
        "event_time": f"2026-11-0{rng.randint(1, 9)}T{rng.randint(0, 23):02d}:"
                      f"{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z",
        "merchant_id": f"merch-{rng.randint(1, 12):03d}",
        "channel": rng.choice(["web", "pos", "mobile"]),
    }


def main() -> None:
    rng = random.Random(20261115)
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    seen: list[dict] = []
    for partition in range(3):
        lines = []
        for offset in range(14):
            n += 1
            value = payload(rng, n)
            kind = (partition * 14 + offset) % 13
            if kind == 3:
                value["customer_id"] = None
            elif kind == 5:
                value["currency"] = rng.choice(["usd", "XYZ", "BTC"])
            elif kind == 7 and seen:
                value = dict(rng.choice(seen))
            elif kind == 9:
                value["amount"] = str(value["amount"])
            elif kind == 11:
                del value["event_time"]
            else:
                seen.append(value)
            msg = {"offset": offset, "key": value.get("customer_id"),
                   "timestamp": 1793836800000 + n * 1000, "value": value}
            lines.append(json.dumps(msg))
        if partition == 1:
            lines.insert(6, '{"offset": 99, "key": "cust-0001", "value": {"tran')
            lines.insert(9, "")
        (OUT / f"partition-{partition}.jsonl").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

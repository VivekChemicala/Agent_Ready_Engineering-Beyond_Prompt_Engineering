# usage-metering

> Synthetic repository for a controlled experiment. Fictional services, no real data.

Owner: `team-finops`. Consumes `metadata.dataset.changed.v1` and keeps a per-owner count of
registered columns for chargeback. It reads only `urn`, `owner` and `len(columns)`, ignores every
other field, and has no dependency on `platform-contracts` (tolerant reader).

```bash
python3 -m pytest -q
python3 -m flake8
```

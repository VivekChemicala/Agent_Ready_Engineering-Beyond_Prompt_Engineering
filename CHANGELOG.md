# Changelog

## 2.4.0
- DP-1501: add optional column `sensitivity` (PUBLIC|INTERNAL|CONFIDENTIAL|PII; absent = INTERNAL) to `metadata.columns.response.v1` and `metadata.dataset.changed.v1`; add `metadata.dataset.column.sensitivity.request.v1` for `PUT /v1/datasets/{urn}/columns/{column}/sensitivity`.

## 2.3.0
- DP-1310: add `metadata.dataset.owner.request.v1` for `PUT /v1/datasets/{urn}/owner`.

## 2.2.0
- DP-1204: add `tags` to columns (source system tags, lower-case strings).

## 2.1.0
- DP-1102: add `metadata.dataset.changed.v1` event.

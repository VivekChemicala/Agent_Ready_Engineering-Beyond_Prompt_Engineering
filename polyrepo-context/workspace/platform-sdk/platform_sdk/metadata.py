from __future__ import annotations

from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str
    nullable: bool = True


@dataclass(frozen=True)
class Dataset:
    urn: str
    name: str
    domain: str
    owner: str


class MetadataClient:
    def __init__(self, base_url: str, session=None):
        self.base_url = base_url.rstrip("/")
        self.http = session or requests.Session()

    def get_dataset(self, urn: str) -> Dataset:
        body = self.http.get(f"{self.base_url}/v1/datasets/{urn}").json()
        return Dataset(urn=body["urn"], name=body["name"], domain=body["domain"],
                       owner=body["owner"])

    def get_columns(self, urn: str) -> list[Column]:
        body = self.http.get(f"{self.base_url}/v1/datasets/{urn}/columns").json()
        return [Column(name=c["name"], data_type=c["data_type"],
                       nullable=c.get("nullable", True)) for c in body["columns"]]

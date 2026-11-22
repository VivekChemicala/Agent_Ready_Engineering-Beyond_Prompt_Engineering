"""Tiny router standing in for the HTTP server."""
import re

from metadata_graph.api import ROUTES, error
from metadata_graph.events import EventPublisher
from metadata_graph.store import GraphStore


def _compile(pattern: str):
    return re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")


class App:
    def __init__(self, store: GraphStore | None = None, sink: list | None = None):
        self.store = store or GraphStore()
        self.sink = sink if sink is not None else []
        self.events = EventPublisher(self.sink)

    def handle(self, method: str, path: str, body=None, headers: dict | None = None):
        for m, pattern, fn in ROUTES:
            match = _compile(pattern).match(path)
            if m == method and match:
                return fn(self.store, self.events, match.groupdict(), body, headers or {})
        return error(404, "NOT_FOUND", f"no route {method} {path}")

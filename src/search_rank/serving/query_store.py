"""Validated curated-query store; arbitrary product input is intentionally absent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

EscIRelevance = Literal["Exact", "Substitute", "Complement", "Irrelevant"]


@dataclass(frozen=True)
class CuratedProduct:
    product_id: str
    title: str
    text: str
    esci_label: EscIRelevance | None = None


@dataclass(frozen=True)
class CuratedQuery:
    query_id: str
    query: str
    products: tuple[CuratedProduct, ...]


class QueryStore:
    def __init__(self, queries: list[CuratedQuery]) -> None:
        if not queries:
            raise ValueError("curated query store must not be empty")
        self._queries = {query.query_id: query for query in queries}
        if len(self._queries) != len(queries):
            raise ValueError("curated query IDs must be unique")
        for query in queries:
            if not 1 <= len(query.products) <= 40:
                raise ValueError(f"query {query.query_id!r} must contain between 1 and 40 products")
            ids = [product.product_id for product in query.products]
            if len(ids) != len(set(ids)):
                raise ValueError(f"query {query.query_id!r} has duplicate products")

    @classmethod
    def from_json(cls, path: str | Path) -> QueryStore:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        queries = []
        for item in payload["queries"]:
            products = tuple(CuratedProduct(**product) for product in item["products"])
            queries.append(
                CuratedQuery(
                    query_id=str(item["query_id"]), query=str(item["query"]), products=products
                )
            )
        return cls(queries)

    def get(self, query_id: str) -> CuratedQuery:
        try:
            return self._queries[query_id]
        except KeyError as exc:
            raise KeyError(f"unknown curated query: {query_id}") from exc

    def search(self, text: str = "", *, limit: int = 20) -> list[CuratedQuery]:
        if not 1 <= limit <= 50:
            raise ValueError("query list limit must be between 1 and 50")
        needle = text.strip().casefold()
        matches = [
            query
            for query in self._queries.values()
            if not needle or needle in query.query.casefold() or needle in query.query_id.casefold()
        ]
        return sorted(matches, key=lambda item: (item.query.casefold(), item.query_id))[:limit]


def write_curated_queries(path: str | Path, queries: list[CuratedQuery]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0.0",
        "queries": [
            {
                "query_id": query.query_id,
                "query": query.query,
                "products": [product.__dict__ for product in query.products],
            }
            for query in queries
        ],
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output

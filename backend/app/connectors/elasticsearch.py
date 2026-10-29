"""Elasticsearch connector: PIT + search_after only (never from/size paging)."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from elasticsearch import Elasticsearch

from app.config import SCAN_KEYWORDS, SCAN_LEVELS, Settings

logger = logging.getLogger(__name__)

PIT_KEEP_ALIVE = "2m"


@dataclass(frozen=True)
class LogRecord:
    timestamp: datetime
    service: str
    host: str | None
    message: str
    es_id: str
    index: str


def make_client(s: Settings) -> Elasticsearch:
    kwargs: dict[str, Any] = {}
    if s.es_api_key:
        kwargs["api_key"] = s.es_api_key
    if s.es_ca_cert:
        kwargs["ca_certs"] = s.es_ca_cert
    return Elasticsearch(s.es_url, request_timeout=30, **kwargs)


def build_query_string() -> str:
    """Levels + WARNING alias + keywords, per spec 5.2 defaults."""
    terms = list(SCAN_LEVELS)
    if "WARN" in terms:
        terms.append("WARNING")
    terms.extend(SCAN_KEYWORDS)
    return " OR ".join(terms)


def build_query(s: Settings, window_start: datetime, window_end: datetime) -> dict[str, Any]:
    return {
        "bool": {
            "filter": [
                {"range": {"@timestamp": {"gt": window_start.isoformat(), "lte": window_end.isoformat()}}},
                {"query_string": {"default_field": s.es_message_field, "query": build_query_string()}},
            ]
        }
    }


def _dig(source: dict[str, Any], path: str) -> Any:
    if path in source:
        return source[path]
    cur: Any = source
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def count_matching(client: Elasticsearch, s: Settings, window_start: datetime, window_end: datetime) -> int:
    resp = client.count(index=s.es_index_pattern, query=build_query(s, window_start, window_end))
    return int(resp["count"])


def fetch_records(
    client: Elasticsearch, s: Settings, window_start: datetime, window_end: datetime
) -> Iterator[LogRecord]:
    fields = ["@timestamp", s.es_message_field, s.es_service_field, s.es_host_field]
    query = build_query(s, window_start, window_end)
    pit_id = client.open_point_in_time(index=s.es_index_pattern, keep_alive=PIT_KEEP_ALIVE)["id"]
    try:
        search_after: list[Any] | None = None
        while True:
            resp = client.search(
                pit={"id": pit_id, "keep_alive": PIT_KEEP_ALIVE},
                query=query,
                sort=[{"@timestamp": "asc"}, {"_shard_doc": "asc"}],
                size=s.es_page_size,
                source=fields,
                track_total_hits=False,
                **({"search_after": search_after} if search_after else {}),
            )
            pit_id = resp.get("pit_id", pit_id)
            hits = resp["hits"]["hits"]
            if not hits:
                return
            for hit in hits:
                src = hit["_source"]
                message = _dig(src, s.es_message_field)
                ts = src.get("@timestamp")
                if not isinstance(message, str) or not ts:
                    logger.warning("skipping ES doc %s without message/timestamp", hit["_id"])
                    continue
                yield LogRecord(
                    timestamp=datetime.fromisoformat(ts.replace("Z", "+00:00")),
                    service=str(_dig(src, s.es_service_field) or "unknown"),
                    host=_dig(src, s.es_host_field),
                    message=message,
                    es_id=hit["_id"],
                    index=hit["_index"],
                )
            search_after = hits[-1]["sort"]
    finally:
        try:
            client.close_point_in_time(id=pit_id)
        except Exception:  # noqa: BLE001 - PIT expires on its own; don't mask the real error
            logger.warning("failed to close point in time", exc_info=True)

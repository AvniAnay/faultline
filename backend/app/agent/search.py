"""Tavily web search wrapper. Queries must be RedactedText."""

import logging
from dataclasses import dataclass
from typing import Protocol

from langchain_tavily import TavilySearch

from app.config import Settings
from app.pipeline.run_stats import StatsTracker
from app.redaction.engine import RedactedText, require_redacted

logger = logging.getLogger(__name__)
CONTENT_CHARS = 400


class SearchError(Exception):
    pass


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    content: str  # truncated


class WebSearch(Protocol):
    def search(self, query: RedactedText, tracker: StatsTracker) -> list[SearchHit]:
        """Raises SearchError on failure."""


class TavilyWebSearch:
    def __init__(self, s: Settings) -> None:
        self._tool = TavilySearch(max_results=5, search_depth="basic", tavily_api_key=s.tavily_api_key or None)

    def search(self, query: RedactedText, tracker: StatsTracker) -> list[SearchHit]:
        q = require_redacted(query)
        tracker.add(tavily_calls=1)
        try:
            resp = self._tool.invoke({"query": q})
        except Exception as exc:
            logger.warning("Tavily call failed: %s", type(exc).__name__)
            raise SearchError(type(exc).__name__) from exc
        if not isinstance(resp, dict) or "results" not in resp:
            raise SearchError("unexpected Tavily response")
        return [
            SearchHit(r.get("url", ""), str(r.get("title", ""))[:120], str(r.get("content", ""))[:CONTENT_CHARS])
            for r in resp["results"]
            if r.get("url")
        ]

"""Groq LLM wrapper: structured output, rate limiting, call/token accounting."""

import logging
import time
from typing import Protocol, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_groq import ChatGroq
from pydantic import BaseModel

from app.config import Settings
from app.pipeline.run_stats import StatsTracker
from app.redaction.engine import RedactedText, require_redacted

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


class StructuredLLM(Protocol):
    def structured(self, schema: type[T], system: str, data: RedactedText, tracker: StatsTracker) -> T:
        """Raises LLMError on any failure."""


class GroqLLM:
    def __init__(self, s: Settings) -> None:
        limiter = InMemoryRateLimiter(
            requests_per_second=s.groq_requests_per_minute / 60, check_every_n_seconds=0.1, max_bucket_size=1
        )
        self._chat = ChatGroq(
            model=s.groq_model, temperature=0, max_retries=3, api_key=s.groq_api_key or None, rate_limiter=limiter
        )

    def structured(self, schema: type[T], system: str, data: RedactedText, tracker: StatsTracker) -> T:
        text = require_redacted(data)
        started = time.monotonic()
        tracker.add(llm_calls=1)
        try:
            out = self._chat.with_structured_output(schema, include_raw=True).invoke(
                [SystemMessage(content=system), HumanMessage(content=text)]
            )
        except Exception as exc:
            logger.warning("LLM call failed after %.1fs: %s", time.monotonic() - started, type(exc).__name__)
            raise LLMError(type(exc).__name__) from exc
        usage = getattr(out.get("raw"), "usage_metadata", None) or {}
        prompt, completion = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        tracker.add_tokens(prompt, completion)
        logger.info("LLM call ok in %.1fs (tokens %d+%d)", time.monotonic() - started, prompt, completion)
        parsed = out.get("parsed")
        if parsed is None:
            raise LLMError("unparseable structured output")
        return parsed

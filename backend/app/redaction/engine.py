"""redact() is the single entry point; RedactedText is the only type storage/LLM/Tavily/email accept."""

import logging
from dataclasses import dataclass, field
from functools import lru_cache

from app.config import get_settings
from app.redaction.rules import RedactionRule, build_rules

logger = logging.getLogger(__name__)

ALLOWLIST = ("api.stripe.com",)
_CREATE = object()


class RedactedText:
    """Text that has passed through redact() (or was derived from such text)."""

    __slots__ = ("_text",)

    def __init__(self, text: str, _token: object = None) -> None:
        if _token is not _CREATE:
            raise TypeError("RedactedText can only be created by redact() or RedactedText.derive()")
        self._text = text

    @property
    def text(self) -> str:
        return self._text

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return f"RedactedText({self._text[:60]!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RedactedText) and other._text == self._text

    def __hash__(self) -> int:
        return hash(self._text)

    def truncate(self, n: int) -> "RedactedText":
        return RedactedText(self._text[:n], _CREATE)

    @staticmethod
    def derive(parent: "RedactedText", text: str) -> "RedactedText":
        """Wrap text computed purely from already-redacted text (e.g. a Drain3 template)."""
        if not isinstance(parent, RedactedText):
            raise TypeError("parent must be RedactedText")
        return RedactedText(text, _CREATE)


def require_redacted(value: object) -> str:
    """Guard for storage/outbound functions: returns the text, rejects plain str."""
    if not isinstance(value, RedactedText):
        raise TypeError("expected RedactedText, got " + type(value).__name__)
    return value.text


@dataclass
class RedactionResult:
    text: RedactedText
    counts: dict[str, int] = field(default_factory=dict)


class RedactionError(Exception):
    pass


@lru_cache
def _default_rules() -> list[RedactionRule]:
    return build_rules(get_settings().internal_host_suffixes)


def redact(text: str, rules: list[RedactionRule] | None = None) -> RedactionResult:
    """Apply all rules in order. Raises RedactionError (caller must drop the line)."""
    try:
        rules = rules if rules is not None else _default_rules()
        counts: dict[str, int] = {}
        # Protect allowlisted values with sentinels so no rule touches them.
        for i, allowed in enumerate(ALLOWLIST):
            text = text.replace(allowed, f"\x00{i}\x00")
        for rule in rules:
            n = 0

            def sub(m, rule=rule):
                nonlocal n
                if rule.validator and not rule.validator(m.group(0)):
                    return m.group(0)
                n += 1
                return rule.repl(m) if rule.repl else rule.placeholder

            text = rule.pattern.sub(sub, text)
            if n:
                counts[rule.name] = n
        for i, allowed in enumerate(ALLOWLIST):
            text = text.replace(f"\x00{i}\x00", allowed)
        return RedactionResult(RedactedText(text, _CREATE), counts)
    except Exception as exc:  # fail closed
        raise RedactionError(str(exc)) from exc


def redact_user_text(text: str | None) -> RedactedText | None:
    """Free text from users (comments, edited resolutions). Raises RedactionError on failure."""
    return None if text is None else redact(text).text

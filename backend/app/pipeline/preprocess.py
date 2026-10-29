"""Prefix stripping, level extraction/normalization, stack-trace trimming (spec 5.3)."""

import re
from dataclasses import dataclass

from app.config import SCAN_KEYWORDS, SCAN_LEVELS

PREFIX_PATTERNS = [
    # Java / Logback
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[[^\]]+\] (?P<level>[A-Z]+)\s+\S+ -",
    # Python logging
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} - \S+ - (?P<level>[A-Z]+) -",
    # Node.js
    r"^\[\d{4}-\d{2}-\d{2}T[\d:.]+Z\] (?P<level>[A-Z]+) \([^)]*\):",
    # Nginx error log
    r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} \[(?P<level>[a-z]+)\] \d+#\d+: \*\d+",
    # PostgreSQL
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} UTC \[\d+\] (?P<level>[A-Z0-9]+):\s+",
]
_PREFIXES = [re.compile(p) for p in PREFIX_PATTERNS]

LEVEL_ALIASES = {
    "WARNING": "WARN",
    "CRIT": "CRITICAL",
    "ALERT": "CRITICAL",
    "EMERG": "FATAL",
    "PANIC": "FATAL",
    "SEVERE": "ERROR",
    "ERR": "ERROR",
}
_LEVEL_WORD = re.compile(r"\b(FATAL|CRITICAL|ERROR|WARN(?:ING)?)\b")
_FRAME = re.compile(r"^\s+(?:at\s+\S|File\s+\")")


@dataclass(frozen=True)
class Preprocessed:
    level: str
    text: str  # prefix-stripped, stack-trimmed, whitespace-normalized (NOT yet redacted)


def normalize_level(raw: str) -> str:
    up = raw.upper()
    return LEVEL_ALIASES.get(up, up)


def trim_stack(text: str, app_prefixes: list[str], max_frames: int) -> str:
    """Keep non-frame lines plus the first `max_frames` application frames."""
    out: list[str] = []
    kept = 0
    last_frame_kept: bool | None = None  # None: previous line was not a frame
    for line in text.split("\n"):
        if _FRAME.match(line):
            keep = kept < max_frames and any(p in line for p in app_prefixes)
            if keep:
                kept += 1
                out.append(line)
            last_frame_kept = keep
        elif last_frame_kept is not None and line.startswith("    ") and line.strip():
            # source line printed under a Python "File ..." frame
            if last_frame_kept:
                out.append(line)
            last_frame_kept = None
        else:
            out.append(line)
            last_frame_kept = None
    return "\n".join(out)


def preprocess(
    message: str, app_prefixes: list[str], max_frames: int = 3, max_chars: int = 4000
) -> Preprocessed | None:
    """Returns None when the line's level is not in the scan levels."""
    body = message
    level: str | None = None
    for pattern in _PREFIXES:
        m = pattern.match(message)
        if m:
            level = normalize_level(m.group("level"))
            body = message[m.end():]
            break
    if level is None:
        m = _LEVEL_WORD.search(message)
        if m:
            level = normalize_level(m.group(1))
        else:
            level = next((lvl for kw, lvl in SCAN_KEYWORDS.items() if kw in message), None)
    if level is None or level not in SCAN_LEVELS:
        return None
    body = trim_stack(body.strip(), app_prefixes, max_frames)
    body = re.sub(r"\s+", " ", body).strip()[:max_chars]
    return Preprocessed(level=level, text=body)

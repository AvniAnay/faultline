"""Ordered redaction rules (spec 5.4 #1-11). Rules #12 (custom IDs) and #13 (entropy) are deferred."""

import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RedactionRule:
    name: str
    pattern: re.Pattern[str]
    placeholder: str
    validator: Callable[[str], bool] | None = None
    # Optional custom replacement (regex match -> str); default is the placeholder
    repl: Callable[[re.Match[str]], str] | None = field(default=None, compare=False)


def luhn_valid(text: str) -> bool:
    digits = [int(c) for c in text if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _valid_ipv4(text: str) -> bool:
    try:
        ipaddress.IPv4Address(text)
    except ValueError:
        return False
    return True


def _valid_ipv6(text: str) -> bool:
    try:
        ipaddress.IPv6Address(text)
    except ValueError:
        return False
    return True


_NOT_PLACEHOLDER = r"(?!<[A-Z_]+>)"

_KEYS = r"(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|client[_-]?secret)"

_IPV4 = r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\w]|\.\d)"
_IPV6 = r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])"


def build_rules(internal_suffixes: list[str]) -> list[RedactionRule]:
    suffix = "|".join(re.escape(s) for s in internal_suffixes)
    host = rf"(?:[A-Za-z0-9-]+\.)*[A-Za-z0-9-]+(?:{suffix})(?![\w-])" if suffix else r"(?!x)x"
    rules = [
        RedactionRule(
            "private_key",
            re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
            "<PRIVATE_KEY>",
        ),
        RedactionRule(
            "conn_string",
            re.compile(
                r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s@/]+@\S+"
                r"|\bjdbc:[^\s]*?password=[^\s&;]+[^\s]*",
                re.I,
            ),
            "<CONN_STRING>",
        ),
        RedactionRule("jwt", re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]*"), "<JWT>"),
        RedactionRule(
            "auth_header",
            re.compile(
                r"(?:(?P<scheme>\bBearer)\s+" + _NOT_PLACEHOLDER + r"[A-Za-z0-9._~+/=-]{8,}"
                r"|(?<=Authorization: )(?P<scheme2>Basic)\s+" + _NOT_PLACEHOLDER + r"[A-Za-z0-9+/=]{6,})",
                re.I,
            ),
            "<TOKEN>",
            repl=lambda m: f"{m.group('scheme') or m.group('scheme2')} <TOKEN>",
        ),
        RedactionRule(
            "secret_kv",
            re.compile(
                rf"(?P<key>[\w.-]*{_KEYS}[\w.-]*)"
                r"(?P<sep>\"\s*:\s*\"|'\s*:\s*'|%3[Dd]|\s*[=:]\s*\"|\s*[=:]\s*'|\s*[=:]\s*)"
                + _NOT_PLACEHOLDER
                + r"(?P<val>[^\s\"'&,;)\]}]+)",
                re.I,
            ),
            "<SECRET>",
            repl=lambda m: f"{m.group('key')}{m.group('sep')}<SECRET>",
        ),
        RedactionRule("cloud_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "<CLOUD_KEY>"),
        RedactionRule("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"), "<EMAIL>"),
        RedactionRule("card", re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])"), "<CARD>", luhn_valid),
        RedactionRule("ipv4", re.compile(_IPV4), "<IP>", _valid_ipv4),
        RedactionRule("ipv6", re.compile(_IPV6), "<IP>", _valid_ipv6),
        RedactionRule("internal_url", re.compile(rf"\bhttps?://{host}(?::\d+)?[^\s\"']*", re.I), "<URL>"),
        RedactionRule("internal_host", re.compile(rf"\b{host}", re.I), "<HOST>"),
        RedactionRule(
            "phone",
            re.compile(
                r"(?<![\w+])\+91[ -]?\d{5}[ -]?\d{5}(?!\d)"
                r"|(?<![\w+])\+\d{1,3}[ -]\d[\d -]{7,12}\d(?!\d)"
                r"|(?<![\w.-])[6-9]\d{9}(?![\w])"
            ),
            "<PHONE>",
        ),
    ]
    return rules

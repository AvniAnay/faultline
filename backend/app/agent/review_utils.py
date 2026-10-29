"""Apply reviewer edits on top of a proposed item."""

from typing import Any


def effective(proposed: dict[str, Any], edited: dict[str, Any] | None) -> dict[str, Any]:
    """Returns {category, severity, resolution: {...}} after applying edits."""
    edited = edited or {}
    resolution = dict(proposed["resolution"])
    for key, value in (edited.get("resolution") or {}).items():
        if value is not None:
            resolution[key] = value
    return {
        "category": edited.get("category") or proposed["category"],
        "severity": edited.get("severity") or proposed["severity"],
        "resolution": resolution,
    }

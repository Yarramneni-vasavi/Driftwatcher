"""Truncation and redaction for logs (plan sec. 8.5).

Strings longer than `max_value_chars` are truncated with a length
suffix. Lists show their count plus the first `max_list_items` items.
Keys matching `redact_keys` become `***`. API key values are never
logged; the key variable name and whether it is set may be.
"""

from __future__ import annotations


def summarize_value(
    value: object,
    max_chars: int = 120,
    max_items: int = 3,
    redact_keys: tuple[str, ...] = (),
) -> object:
    if isinstance(value, dict):
        return {
            str(k): (
                "***"
                if _redacted(str(k), redact_keys)
                else summarize_value(v, max_chars, max_items, redact_keys)
            )
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        items = list(value)
        shown = [
            summarize_value(v, max_chars, max_items, redact_keys)
            for v in items[:max_items]
        ]
        if len(items) > max_items:
            return {"count": len(items), "items": shown}
        return shown
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + f"...({len(value)} chars)"
    return value


def summarize(
    payload: object,
    max_chars: int = 120,
    max_items: int = 3,
    redact_keys: tuple[str, ...] = (),
) -> dict:
    """Summarize a payload via its log_summary(), then truncate/redact."""
    if hasattr(payload, "log_summary"):
        raw = payload.log_summary()
    elif isinstance(payload, dict):
        raw = payload
    else:
        raw = {"value": str(payload)}
    if not isinstance(raw, dict):
        raw = {"value": raw}
    return summarize_value(raw, max_chars, max_items, redact_keys)  # type: ignore[return-value]


def format_params(params: dict) -> str:
    """Compact `k=v k2=v2` rendering for pretty console lines."""
    parts: list[str] = []
    for key, value in params.items():
        if isinstance(value, dict) and "count" in value and "items" in value:
            rendered = f"{value['count']} total: {value['items']}"
        elif isinstance(value, dict):
            rendered = " ".join(f"{k}={v}" for k, v in value.items())
        elif isinstance(value, list):
            rendered = "[" + ", ".join(str(v) for v in value) + "]"
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return " ".join(parts)


def _redacted(key: str, redact_keys: tuple[str, ...]) -> bool:
    lowered = key.lower()
    return any(token.lower() in lowered for token in redact_keys)

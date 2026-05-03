"""Utility helpers for LangGraph configurable runtime values."""

from __future__ import annotations

from typing import Any

from langgraph.config import get_config


def resolve_configurable_value(key: str, default_value: str) -> str:
    """Resolve configurable value by key, then thread_id, then default."""
    try:
        config: dict[str, Any] = get_config()
    except RuntimeError:
        return default_value

    configurable = config.get("configurable") or {}
    return configurable.get(key) or configurable.get("thread_id", default_value)

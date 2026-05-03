"""Centralized runtime settings for the LangGraph app."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _get_required(name: str) -> str:
    """Read a required environment variable or raise immediately."""
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _get_bool(name: str, default: bool = False) -> bool:
    """Parse a bool environment value with common truthy forms."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Typed settings loaded from environment variables."""

    langsmith_api_key: str
    langchain_tracing_v2: bool
    openai_api_key: str
    openai_base_url: str
    openai_model_name: str
    tavily_api_key: str

    @classmethod
    def from_env(cls) -> Settings:
        """Create a settings instance from process environment."""
        return cls(
            langsmith_api_key=_get_required("LANGSMITH_API_KEY"),
            langchain_tracing_v2=_get_bool("LANGCHAIN_TRACING_V2", default=True),
            openai_api_key=_get_required("OPENAI_API_KEY"),
            openai_base_url=_get_required("OPENAI_BASE_URL"),
            openai_model_name=_get_required("OPENAI_MODEL_NAME"),
            tavily_api_key=_get_required("TAVILY_API_KEY"),
        )


settings = Settings.from_env()

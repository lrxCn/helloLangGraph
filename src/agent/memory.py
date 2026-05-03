"""Mem0 memory manager backed by local Qdrant."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from mem0 import Memory

from src.config.settings import settings


class MemoryManager:
    """Encapsulate Mem0 long-term memory operations with async wrappers."""

    def __init__(self) -> None:
        self._memory: Memory | None = None
        self._init_lock = asyncio.Lock()

    async def _check_qdrant_online(self) -> None:
        """Check Qdrant root path availability before Mem0 initialization."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(settings.qdrant_url)
            if response.status_code >= 500:
                raise RuntimeError(f"Qdrant 返回异常状态码: {response.status_code}")
        except Exception as exc:
            raise RuntimeError(
                "Qdrant 连接失败，请检查代理设置，并建议使用 127.0.0.1 替换 localhost。"
            ) from exc

    def _build_mem0_config(self) -> dict[str, Any]:
        """Build Mem0 config for local Qdrant + SiliconFlow OpenAI-compatible APIs."""
        return {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "url": settings.qdrant_url,
                    "collection_name": "mem0",
                    "embedding_model_dims": 1024,
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "api_key": settings.mem0_api_key,
                    "model": settings.openai_model_name,
                    "openai_base_url": settings.mem0_base_url,
                    "temperature": 0,
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "api_key": settings.mem0_api_key,
                    "model": settings.mem0_embedding_model,
                    "openai_base_url": settings.mem0_base_url,
                },
            },
        }

    async def _ensure_memory(self) -> None:
        """Initialize Mem0 client lazily and only once."""
        if self._memory is not None:
            return
        async with self._init_lock:
            if self._memory is not None:
                return
            await self._check_qdrant_online()
            try:
                config = self._build_mem0_config()
                self._memory = await asyncio.to_thread(Memory.from_config, config)
            except Exception as exc:
                raise RuntimeError(
                    "Mem0 初始化失败，请检查 LLM/Embedding 配置。"
                    "若出现向量维度错误，请删除 Qdrant 中的 mem0、mem0_entities、mem0migrations，"
                    "并按 1024 维重新创建集合。"
                ) from exc

    async def add_memories(self, user_id: str, text: str) -> None:
        """Persist conversation text as long-term memory for a specific user."""
        if not text.strip():
            return
        await self._ensure_memory()
        assert self._memory is not None

        def _add() -> Any:
            return self._memory.add(
                [{"role": "user", "content": text}],
                user_id=user_id,
            )

        try:
            await asyncio.to_thread(_add)
        except Exception as exc:
            raise RuntimeError("写入 Mem0 记忆失败。") from exc

    def _normalize_search_results(self, result: Any) -> list[dict[str, Any] | str]:
        """Normalize Mem0 search return format to a list."""
        if isinstance(result, dict):
            maybe_results = result.get("results")
            if isinstance(maybe_results, list):
                return maybe_results
            return []
        if isinstance(result, list):
            return result
        return []

    async def search_memories(self, user_id: str, query: str) -> list[str]:
        """Search user-scoped memories and return clean text snippets."""
        if not query.strip():
            return []
        await self._ensure_memory()
        assert self._memory is not None

        def _search() -> Any:
            return self._memory.search(
                query=query,
                top_k=settings.mem0_search_top_k,
                filters={"user_id": user_id},
            )

        try:
            raw_result = await asyncio.to_thread(_search)
        except Exception as exc:
            raise RuntimeError("检索 Mem0 记忆失败。") from exc

        items = self._normalize_search_results(raw_result)
        snippets: list[str] = []
        for item in items:
            if isinstance(item, str) and item.strip():
                snippets.append(item.strip())
                continue
            if isinstance(item, dict):
                text = (
                    item.get("memory")
                    or item.get("text")
                    or item.get("content")
                    or item.get("fact")
                )
                if isinstance(text, str) and text.strip():
                    snippets.append(text.strip())
        return snippets

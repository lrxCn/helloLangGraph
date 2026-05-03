import asyncio

from agent.memory import MemoryManager
from config.settings import settings
from util.configurable import resolve_configurable_value


def test_settings_contains_mem0_fields() -> None:
    assert settings.mem0_api_key
    assert settings.mem0_base_url
    assert settings.mem0_embedding_model
    assert settings.qdrant_url
    assert "{memory_section}" in settings.system_prompt_template


def test_resolve_configurable_value_prefers_explicit_key(monkeypatch) -> None:
    class _FakeConfig(dict):
        pass

    fake_config = _FakeConfig(configurable={"user_id": "u-1", "thread_id": "t-1"})
    monkeypatch.setattr("util.configurable.get_config", lambda: fake_config)

    assert resolve_configurable_value("user_id", "default_user") == "u-1"


def test_resolve_configurable_value_falls_back_to_thread_id(monkeypatch) -> None:
    class _FakeConfig(dict):
        pass

    fake_config = _FakeConfig(configurable={"thread_id": "t-1"})
    monkeypatch.setattr("util.configurable.get_config", lambda: fake_config)

    assert resolve_configurable_value("user_id", "default_user") == "t-1"


def test_search_memories_uses_results_field_without_iterating_keys() -> None:
    manager = MemoryManager.__new__(MemoryManager)

    class _FakeMemory:
        def search(self, *_args, **_kwargs):
            return {"results": [{"memory": "喜欢吃鱼"}]}

    manager._memory = _FakeMemory()

    result = asyncio.run(manager.search_memories("u-1", "喜欢什么"))
    assert result == ["喜欢吃鱼"]

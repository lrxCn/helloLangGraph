from langgraph.config import get_config


def resolve_configurable_value(key: str, default_value: str) -> str:
    """通用封装 configurable 读取逻辑，优先取指定 key，再回退 thread_id。"""
    config = get_config()
    configurable = config.get("configurable", {})
    return configurable.get(key) or configurable.get("thread_id", default_value)

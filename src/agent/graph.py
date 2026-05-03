"""LangChain create_agent graph with async tool retry middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agent.memory import MemoryManager
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ToolCallRequest,
    after_agent,
    before_model,
    wrap_tool_call,
)
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.runtime import Runtime
from langgraph.types import Command
from src.config.settings import settings
from src.util.configurable import resolve_configurable_value


async def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


async def _invoke_with_retries(operation: Callable[[], Awaitable[Any]]) -> Any:
    """Retry async operation for up to three attempts."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return await operation()
        except Exception:
            if attempt == max_retries - 1:
                return "工具调用失败：重试 3 次后仍然失败"


@wrap_tool_call
async def retry_tool_calls(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
) -> ToolMessage | Command[Any]:
    """Retry tool calls in async flow and downgrade failures to a tool message."""

    async def _call_handler() -> ToolMessage | Command[Any]:
        return await handler(request)

    result = await _invoke_with_retries(_call_handler)
    if isinstance(result, str):
        return ToolMessage(
            content=result,
            tool_call_id=request.tool_call["id"],
        )
    return result


def _message_content(message: BaseMessage | dict[str, Any]) -> str:
    """Extract string content from message object or raw dict."""
    if isinstance(message, BaseMessage):
        if isinstance(message.content, str):
            return message.content
        return ""
    content = message.get("content", "")
    return content if isinstance(content, str) else ""


def _is_user_message(message: BaseMessage | dict[str, Any]) -> bool:
    """Check whether message belongs to user role."""
    if isinstance(message, HumanMessage):
        return True
    if isinstance(message, BaseMessage):
        return message.type == "human"
    return message.get("role") == "user"


def _is_assistant_message(message: BaseMessage | dict[str, Any]) -> bool:
    """Check whether message belongs to assistant/ai role."""
    if isinstance(message, AIMessage):
        return True
    if isinstance(message, BaseMessage):
        return message.type in {"ai", "assistant"}
    return message.get("role") in {"assistant", "ai"}


def _get_latest_message_by_role(
    messages: list[BaseMessage | dict[str, Any]],
    role_checker: Callable[[BaseMessage | dict[str, Any]], bool],
) -> str:
    """Get latest message content that matches role checker."""
    for message in reversed(messages):
        if role_checker(message):
            content = _message_content(message)
            if content.strip():
                return content.strip()
    return ""


memory_manager = MemoryManager()


@before_model
async def inject_memory_middleware(
    state: dict[str, Any],
    runtime: Runtime[Any],
) -> dict[str, Any]:
    """Inject dynamic memory prompt before model execution."""
    _ = runtime
    user_id = resolve_configurable_value("user_id", "default_user")
    messages = state.get("messages", [])
    user_input = _get_latest_message_by_role(messages, _is_user_message)
    memories = await memory_manager.search_memories(user_id=user_id, query=user_input)

    memory_lines = ["## 记忆补充", "- 你也擅长数学和基础计算，可在必要时调用 add 工具。"]
    if memories:
        memory_lines.extend(f"- {memory}" for memory in memories)
    else:
        memory_lines.append("- 如果当前问题缺少相关信息，请严格回复“我不知道。”")
    memory_section = "\n".join(memory_lines)

    memory_msg = SystemMessage(
        id="temp_memory_msg",
        content=settings.system_prompt_template.format(memory_section=memory_section),
    )
    return {"messages": [memory_msg]}


@after_agent
async def archive_memory_middleware(
    state: dict[str, Any],
    runtime: Runtime[Any],
) -> dict[str, Any]:
    """Archive latest conversation into Mem0 and purge temp memory prompt."""
    _ = runtime
    user_id = resolve_configurable_value("user_id", "default_user")
    messages = state.get("messages", [])

    user_input = _get_latest_message_by_role(messages, _is_user_message)
    assistant_output = _get_latest_message_by_role(messages, _is_assistant_message)

    if user_input and assistant_output:
        archive_text = f"用户：{user_input}\n助手：{assistant_output}"
        try:
            await memory_manager.add_memories(user_id=user_id, text=archive_text)
        except RuntimeError:
            pass

    return {"messages": [RemoveMessage(id="temp_memory_msg")]}


model = ChatOpenAI(
    model=settings.openai_model_name,
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
)

agent = create_agent(
    model=model,
    tools=[add],
    middleware=[
        inject_memory_middleware,
        retry_tool_calls,
        archive_memory_middleware,
    ],
    name="math-agent-with-retry",
)

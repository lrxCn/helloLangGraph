"""LangChain create_agent graph with async tool retry middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from config.settings import settings
from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallRequest, wrap_tool_call
from langchain_openai import ChatOpenAI
from langgraph.types import Command
from langchain_core.messages import ToolMessage


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


model = ChatOpenAI(
    model=settings.openai_model_name,
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
)

agent = create_agent(
    model=model,
    tools=[add],
    middleware=[retry_tool_calls],
    system_prompt="你是一个可靠的数学助手，优先使用 add 工具。",
    name="math-agent-with-retry",
)

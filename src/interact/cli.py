"""Command-line interactive chat entrypoint."""

from __future__ import annotations

import asyncio
import argparse
import logging
import warnings
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from prompt_toolkit import PromptSession
from src.agent.graph import agent


def _configure_cli_logging() -> None:
    """Downgrade noisy third-party warnings for local interactive CLI only."""
    noisy_loggers = (
        "mem0.utils.spacy_models",
        "mem0.vector_stores.qdrant",
    )
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.ERROR)

    noisy_warning_keywords = (
        "spacy",
        "spaCy",
        "bm25",
        "BM25",
        "rank_bm25",
    )
    for keyword in noisy_warning_keywords:
        warnings.filterwarnings(
            "ignore",
            message=rf".*{keyword}.*",
            category=Warning,
        )


def _extract_text_content(content: Any) -> str:
    """Extract printable text from AI message content payload."""
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text_value = item.get("text")
                if isinstance(text_value, str) and text_value.strip():
                    texts.append(text_value.strip())
        return "\n".join(texts).strip()

    return ""


def _extract_latest_ai_reply(messages: list[BaseMessage | dict[str, Any]]) -> str:
    """Get the latest non-empty AI reply from message history."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            reply = _extract_text_content(message.content)
            if reply:
                return reply
        elif isinstance(message, dict) and message.get("role") in {"assistant", "ai"}:
            reply = _extract_text_content(message.get("content", ""))
            if reply:
                return reply
    return ""


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for interactive chat."""
    parser = argparse.ArgumentParser(description="和 agent 进行命令行对话")
    parser.add_argument(
        "--thread-id",
        dest="thread_id",
        default=None,
        help="显式指定会话 thread_id（默认随机生成）",
    )
    parser.add_argument(
        "--user-id",
        dest="user_id",
        default=None,
        help="显式指定会话 user_id（默认使用 thread_id）",
    )
    return parser.parse_args()


async def chat(user_id: str | None = None, thread_id: str | None = None) -> None:
    """Run an interactive CLI loop with the LangChain agent."""
    print("已进入对话模式，输入 /q 退出。")
    resolved_thread_id = thread_id or uuid4().hex
    resolved_user_id = user_id or thread_id
    if not resolved_user_id:
        resolved_user_id = resolved_thread_id
    config = {
        "configurable": {
            "thread_id": resolved_thread_id,
            "user_id": resolved_user_id,
        }
    }
    session: PromptSession[str] = PromptSession()

    while True:
        try:
            user_input = (await session.prompt_async("你: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出对话。")
            return

        if not user_input:
            continue
        if user_input == "/q":
            print("已退出对话。")
            return

        try:
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=user_input)]},
                config=config,
            )
        except Exception as exc:
            print(f"助手: 调用失败（{exc}）")
            continue

        if not isinstance(result, dict):
            print("助手: 抱歉，我暂时无法处理这个请求。")
            continue

        messages = result.get("messages", [])
        if not isinstance(messages, list):
            print("助手: 抱歉，我暂时无法处理这个请求。")
            continue

        reply = _extract_latest_ai_reply(messages)
        if not reply:
            reply = "抱歉，我暂时无法生成有效回复。"
        print(f"助手: {reply}")


def main() -> None:
    """CLI application entrypoint."""
    args = _parse_args()
    _configure_cli_logging()
    asyncio.run(chat(user_id=args.user_id, thread_id=args.thread_id))


if __name__ == "__main__":
    main()

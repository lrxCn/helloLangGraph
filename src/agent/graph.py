from typing import Any, Callable
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage, RemoveMessage
from langchain.agents.middleware import wrap_tool_call, before_model, after_agent
from langchain_core.tools import tool
from src.config.settings import settings
from src.agent.memory import memory_manager
import logging

logger = logging.getLogger(__name__)
from langchain.messages import RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents import create_agent, AgentState
from langchain.agents.middleware import before_model
from langgraph.runtime import Runtime
from langchain_core.runnables import RunnableConfig
from typing import Any, TypedDict
from src.util.configurable import resolve_configurable_value


# 1. 配置工具
@tool
async def add(a: float, b: float) -> float:
    """计算两个数字的和。

    Args:
        a: 第一个数字
        b: 第二个数字
    """
    return a + b


# 2. 编写带重试机制的异步中间件
@wrap_tool_call
async def retry_middleware(request: Any, handler: Callable) -> Any:
    """
    实现 3 次重试逻辑的中间件。
    若全部失败，则将错误字符串返回给 LLM。
    """
    last_error = None
    for attempt in range(3):
        try:
            # 执行工具调用
            return await handler(request)
        except Exception as e:
            last_error = e
            # 继续重试

    # 3 次均失败，返回错误字符串
    return f"Tool execution failed after 3 attempts. Error: {str(last_error)}"


@before_model
async def inject_memory_middleware(
    state: AgentState, runtime: Runtime
) -> dict[str, Any] | None:
    """在模型调用前检索并注入长期记忆。"""
    messages = state.get("messages", [])
    if not messages or messages[-1].type != "human":
        return None

    user_query = messages[-1].content

    user_id = resolve_configurable_value("user_id", "default_user")

    try:
        memory_context = await memory_manager.search_memories(user_query, user_id)

        # 无论是否有记忆，都注入基础人格；如果有记忆，则额外注入背景
        memory_section = (
            f"\n# 用户记忆库\n<memory>\n{memory_context}\n</memory>\n"
            if memory_context
            else ""
        )

        strict_prompt = settings.SYSTEM_PROMPT_TEMPLATE.format(
            memory_section=memory_section
        )
        # 核心修复：加上固定 ID (temp_memory_msg)
        memory_msg = SystemMessage(content=strict_prompt, id="temp_memory_msg")

        # 核心修复：直接返回新消息，LangGraph 会自动追加，不带 state["messages"] 以防重复
        return {"messages": [memory_msg]}

    except Exception as e:
        logger.warning(f"记忆检索失败: {e}")

    return None


@after_agent
async def archive_memory_middleware(
    state: AgentState, runtime: Runtime
) -> dict[str, Any] | None:
    """在对话流程结束后，将本次互动的关键信息存入 Mem0。"""
    messages = state.get("messages", [])
    if len(messages) < 2:
        return

    user_id = resolve_configurable_value("user_id", "default_user")

    # 提取最后一次有效互动
    user_input = ""
    ai_output = ""
    for msg in reversed(messages):
        # 兼容性处理：支持 ai 和 assistant 两种类型名
        if msg.type in ["human", "user"] and not user_input:
            user_input = msg.content
        if msg.type in ["ai", "assistant"] and not ai_output:
            ai_output = msg.content
        if user_input and ai_output:
            break

    if user_input and ai_output:
        try:
            # 将问答对合并存入记忆
            full_interaction = f"User: {user_input}\nAssistant: {ai_output}"
            await memory_manager.add_memories(full_interaction, user_id)
            logger.info(f"✅ 已将对话归档至 Mem0 (User: {user_id})")
        except Exception as e:
            logger.warning(f"记忆归档失败: {e}")

    # 核心修复：只有当临时指令确实存在于历史记录中时，才执行抹除操作
    if any(getattr(m, "id", None) == "temp_memory_msg" for m in messages):
        return {"messages": [RemoveMessage(id="temp_memory_msg")]}

    return None


# 3. 获取模型配置并初始化 LLM
# 从 src.config.settings 中获取 API Key, Base URL 和 Model Name
llm = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
    model=settings.OPENAI_MODEL_NAME,
    temperature=0,
)

# 4. 构建 Agent
# 使用 create_agent 并配置中间件
agent = create_agent(
    model=llm,
    tools=[add],
    middleware=[retry_middleware, inject_memory_middleware, archive_memory_middleware],
)

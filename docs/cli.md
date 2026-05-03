# CLI 对话使用说明

## 启动命令

```bash
uv run agent-chat
```

启动后进入循环对话：

- 输入提示：`你: `
- 输出提示：`助手: `
- 输入 `/q` 退出

## 会话标识注入（user_id / thread_id）

CLI 支持通过参数把 `user_id` 和 `thread_id` 注入到 LangGraph `configurable`，供 `src/util/configurable.py` 的 `resolve_configurable_value()` 在中间件中读取。

### 参数

- `--thread-id`：显式指定会话 `thread_id`（默认随机生成）
- `--user-id`：显式指定会话 `user_id`（默认等于最终的 `thread_id`）

### 示例

```bash
# 两个都不传：thread_id 随机，user_id = thread_id
uv run agent-chat

# 只传 user_id：thread_id 随机，user_id 使用显式值
uv run agent-chat --user-id alice

# 只传 thread_id：thread_id 使用显式值，user_id = thread_id
uv run agent-chat --thread-id chat-001

# 两个都传：分别使用显式值
uv run agent-chat --thread-id chat-001 --user-id alice
```

## 运行时行为说明

- CLI 使用 `prompt_toolkit` 的 `PromptSession.prompt_async()`，避免异步嵌套问题。
- agent 调用异常会被捕获并友好提示，不会直接导致 CLI 崩溃。
- `messages` 返回结构异常时会输出兜底回复。
- 仅在 CLI 入口降级 mem0 的 spaCy/BM25 噪音日志，不影响其他运行方式。
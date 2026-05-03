---
name: memory-layering
overview: 设计并落地“短期记忆(SQLite) + 中期总结(user_id可复用) + 长期记忆(mem0)”协同方案，先保证线程内稳定，再按 user_id 做可控复用。
todos:
  - id: align-state-schema
    content: 定义并对齐线程状态字段（messages/turn_count/running_summary/last_summary_turn）
    status: pending
  - id: design-dual-trigger
    content: 敲定双触发参数与默认值，确定摘要更新时机
    status: pending
  - id: design-mid-profile-store
    content: 定义user_id中期画像存储接口与覆盖策略
    status: pending
  - id: design-injection-order
    content: 确定before_model注入顺序与冲突去重规则
    status: pending
  - id: design-longterm-policy
    content: 确定mem0准入规则与提炼函数边界
    status: pending
  - id: define-validation-scenarios
    content: 确定四类最小验证场景与通过标准
    status: pending
isProject: false
---

# 短期+中期+长期记忆协同方案

> 目标：把本计划变成“可分块执行、无歧义、可交给任何 AI 按顺序落地”的执行手册。  
> 执行规则：一次只执行一个块；当前块验收通过后再执行下一个块。

## 0. 固定边界（所有块都必须遵守）
- 只能在以下文件中改动：  
  - [src/agent/graph.py](src/agent/graph.py)  
  - [src/agent/memory.py](src/agent/memory.py)  
  - [src/config/settings.py](src/config/settings.py)  
  - [src/agent/summary.py](src/agent/summary.py)（新建）  
  - [src/agent/memory_policy.py](src/agent/memory_policy.py)（新建）  
  - [src/agent/mid_profile_store.py](src/agent/mid_profile_store.py)（新建）
- 禁止改动无关模块；禁止引入重型新依赖。
- 任何阈值必须来自 `settings`，禁止硬编码。
- 所有新增配置项统一从 [src/config/settings.py](src/config/settings.py) 的 `Settings` 读取，不允许在业务代码里直接 `os.getenv(...)`。
- `thread_id` 与 `user_id` 固定分工：  
  - `thread_id`：会话内状态（`messages`/`turn_count`/`running_summary`/`last_summary_turn`）  
  - `user_id`：跨会话状态（`mid_profile_summary` + mem0 长期事实）

## 1. 执行顺序（必须按序）
- BLOCK-00 依赖与环境前置检查
- BLOCK-01 配置项落地
- BLOCK-01.5 checkpointer 落地（SQLite）
- BLOCK-02 摘要能力接入（优先 SummarizationMiddleware）
- BLOCK-03 中期画像存储接口
- BLOCK-04 before_model 注入链路
- BLOCK-05 after_agent 写入链路
- BLOCK-06 图装配与中间件顺序
- BLOCK-07 人工验证清单（工程师执行）
- BLOCK-08 回归与验收清单

## BLOCK-00 依赖与环境前置检查
**目标**：先确保依赖齐全，再开始功能块，避免中途返工。  
**只允许修改**：
- [pyproject.toml](pyproject.toml)
- `uv.lock`（由 `uv` 自动更新）

**现状说明（基于当前仓库）**
- 已有：`langchain`、`langchain-openai`、`langgraph`、`mem0ai[nlp]`、`qdrant-client`。
- 缺少（本方案必需）：`langgraph-checkpoint-sqlite`（SQLite 短期记忆 checkpointer）。
- `SummarizationMiddleware` 属于 `langchain.agents.middleware`，不需要额外安装新包（前提是现有 `langchain` 版本可用）。

**步骤**
- [ ] 1. 执行：`uv sync`
- [ ] 2. 执行：`uv add langgraph-checkpoint-sqlite`
- [ ] 3. 执行：`uv run python -c "from langgraph.checkpoint.sqlite import SqliteSaver; print('ok')"`
- [ ] 4. 执行：`uv run python -c "from langchain.agents.middleware import SummarizationMiddleware; print('ok')"`

**可选依赖（仅在需要时再加）**
- 若后续你坚持精确 token 计数且框架内无法满足，再考虑：`uv add tiktoken`。
- 当前计划默认不加该包（先用 `SummarizationMiddleware` 触发能力）。

**完成定义（DoD）**
- `SqliteSaver` 与 `SummarizationMiddleware` 都可成功 import。
- `pyproject.toml` 中出现 `langgraph-checkpoint-sqlite` 依赖声明。

## BLOCK-01 配置项落地
**目标**：补全记忆与 SQLite 配置来源（`settings` + `.env` + `.env.example`）。  
**只允许修改**：
- [src/config/settings.py](src/config/settings.py)
- `.env`
- `.env.example`

**步骤**
- [ ] 1. 新增 `SHORT_TERM_SUMMARY_INTERVAL: int = 8`
- [ ] 2. 新增 `SHORT_TERM_RECENT_TURNS: int = 4`
- [ ] 3. 新增 `SHORT_TERM_SUMMARY_MAX_CHARS: int = 300`
- [ ] 4. 新增 `MODEL_CONTEXT_WINDOW: int = 32768`
- [ ] 5. 新增 `SUMMARY_TRIGGER_CONTEXT_RATIO: float = 0.5`
- [ ] 6. 新增 `MEM0_SEARCH_TOP_K: int = 5`
- [ ] 7. 为以上配置补最小合法性约束（如 `interval>=1`）
- [ ] 8. 新增 `SHORT_TERM_SQLITE_PATH`（示例：`./data/short_term_memory.sqlite`）
- [ ] 9. 在 `.env` 与 `.env.example` 增加 `SHORT_TERM_SQLITE_PATH` 与上述记忆配置示例值

**完成定义（DoD）**
- 项目可正常 import `settings`，无异常。
- `.env` 与 `.env.example` 都有 SQLite 与记忆相关配置键（键名一致）。

## BLOCK-01.5 checkpointer 落地（SQLite）
**目标**：短期记忆必须通过 SQLite checkpointer 持久化，不允许仅内存态。  
**只允许修改**：
- [src/agent/graph.py](src/agent/graph.py)
- [src/config/settings.py](src/config/settings.py)

**固定约束**
- checkpointer 实现固定为：`langgraph.checkpoint.sqlite` 的 `SqliteSaver`（如需异步再选 `AsyncSqliteSaver`，二选一，不混用）。
- 数据库路径来源固定为：[src/config/settings.py](src/config/settings.py) 中新增的 `settings.short_term_sqlite_path`。
- `create_agent(...)` 必须显式传 `checkpointer=...`。
- `thread_id/user_id` 获取统一走 [src/util/configurable.py](src/util/configurable.py) 的 `resolve_configurable_value(...)`，禁止重复实现获取逻辑。

**步骤**
- [ ] 1. 在 `settings.py` 的 `Settings` 增加 `short_term_sqlite_path` 字段，并从环境变量 `SHORT_TERM_SQLITE_PATH` 读取
- [ ] 2. 在 `graph.py` 增加 SQLite checkpointer 初始化函数（从 `settings.short_term_sqlite_path` 读取路径）
- [ ] 3. 在需要读取 `thread_id/user_id` 的地方统一改为 `resolve_configurable_value(...)`
- [ ] 4. 在 `create_agent(...)` 中注入 `checkpointer=sqlite_checkpointer`
- [ ] 5. 在对外调用示例/说明中固定写明 `{"configurable": {"thread_id": "<id>", "user_id": "<id>"}}`
- [ ] 6. 明确异常处理：SQLite 打开失败时抛可读错误（包含 db 路径）

**完成定义（DoD）**
- 相同 `thread_id` 的两次调用可读到同一会话历史。
- 不同 `thread_id` 的会话互不污染。
- 代码中不存在“仅 MemorySaver 而无 SQLite 持久化”的主链路。

## BLOCK-02 摘要能力接入（优先 SummarizationMiddleware）
**目标**：优先使用 `langchain.agents.middleware.SummarizationMiddleware` 完成摘要触发与摘要维护；做不到的部分再最小补齐。  
**只允许修改/新增**
- [src/agent/summary.py](src/agent/summary.py)（新建）
- [src/agent/memory_policy.py](src/agent/memory_policy.py)（新建）
- [src/agent/graph.py](src/agent/graph.py)

**步骤**
- [ ] 1. 在 `graph.py` 先接入 `SummarizationMiddleware`，使用 `trigger=("tokens", X)` 与 `keep=("messages", Y)`（X/Y 来自 `settings`）
- [ ] 2. 在 `summary.py` 仅保留“中间件能力补丁函数”（例如轮次触发补丁、四段格式化补丁）
- [ ] 3. 若 `SummarizationMiddleware` 无法直接支持“轮次触发”，再增加最小包装逻辑（不能替代中间件主流程）
- [ ] 4. 若中间件摘要格式无法满足四段结构（`目标/约束/进展/待办`），仅增加后处理格式化函数
- [ ] 5. 在 `memory_policy.py` 定义 `should_archive_to_long_term(user_input, assistant_output) -> bool`
- [ ] 6. 定义 `extract_long_term_facts(user_input, assistant_output) -> list[str]`
- [ ] 7. 明确过滤规则：一次性问答/临时中间态不入长期

**完成定义（DoD）**
- 摘要主链路由 `SummarizationMiddleware` 驱动，不是自研摘要主链路。
- 自定义代码仅用于中间件缺口补齐（可在注释中注明“为什么必须补”）。
- 长期准入两个函数可被其他模块导入。

## BLOCK-03 中期画像存储接口
**目标**：把“按 user_id 复用”的存取抽象独立出来。  
**只允许新增**
- [src/agent/mid_profile_store.py](src/agent/mid_profile_store.py)

**步骤**
- [ ] 1. 定义 `get_mid_profile(user_id: str) -> str`
- [ ] 2. 定义 `upsert_mid_profile(user_id: str, summary: str) -> None`
- [ ] 3. 定义“显著变化再更新”判定（可先用字符串相等/长度差阈值）
- [ ] 4. 增加异常兜底：存储失败不抛出致命错误

**完成定义（DoD）**
- 上层可通过这两个函数读写 `user_id` 画像，不关心底层实现。

## BLOCK-04 before_model 注入链路
**目标**：注入顺序固定，保证上下文可控。  
**只允许修改**
- [src/agent/graph.py](src/agent/graph.py)
- [src/agent/memory.py](src/agent/memory.py)（仅必要调用）

**步骤**
- [ ] 1. 在 `before_model` 先读取 `thread_id` 线程态（最近 N 轮 + running_summary）
- [ ] 2. 读取 `user_id` 的 `mid_profile_summary`
- [ ] 3. 调用 mem0 检索（`top_k = settings.MEM0_SEARCH_TOP_K`）
- [ ] 4. 按固定顺序拼注入内容：`短期窗口 -> 线程中期 -> user中期 -> mem0`
- [ ] 5. 注入消息 `id` 固定为 `temp_memory_msg`
- [ ] 6. 当某层为空时，保留层标题但填“无”

**完成定义（DoD）**
- 同一轮注入文本结构稳定，不随调用者变化。

## BLOCK-05 after_agent 写入链路
**目标**：每轮更新线程态、按需更新中期、严格准入长期。  
**只允许修改**
- [src/agent/graph.py](src/agent/graph.py)
- [src/agent/memory.py](src/agent/memory.py)
- [src/agent/summary.py](src/agent/summary.py)
- [src/agent/memory_policy.py](src/agent/memory_policy.py)
- [src/agent/mid_profile_store.py](src/agent/mid_profile_store.py)

**步骤**
- [ ] 1. 每轮 `turn_count += 1`
- [ ] 2. 优先读取 `SummarizationMiddleware` 产出的摘要结果并同步到 `running_summary`
- [ ] 3. 若需轮次触发补丁，仅在中间件未触发时补一次最小摘要更新
- [ ] 4. 更新 `last_summary_turn`（仅在摘要实际变化时）
- [ ] 5. 若线程摘要有显著变化：`upsert_mid_profile(user_id, running_summary)`
- [ ] 6. 调用长期准入函数，只有通过才写 mem0
- [ ] 7. 清理临时注入消息：`RemoveMessage(id="temp_memory_msg")`

**完成定义（DoD）**
- 不再出现“每轮整段写 mem0”的行为。
- 线程摘要与 user 画像更新频率可控（非每轮强制写）。
- 在可行范围内优先复用 `SummarizationMiddleware` 成果。

## BLOCK-06 图装配与中间件顺序
**目标**：把主流程顺序固定，避免不同 AI 任意排列。  
**只允许修改**
- [src/agent/graph.py](src/agent/graph.py)

**步骤**
- [ ] 1. 确认 middleware 顺序固定为：`before_model` -> `SummarizationMiddleware` -> `wrap_tool_call` -> `after_agent`
- [ ] 2. 保留现有重试中间件，不改语义
- [ ] 3. `create_agent(...)` 中显式包含 `checkpointer=sqlite_checkpointer`
- [ ] 4. 所有新逻辑通过函数调用，不在 `create_agent(...)` 里内联复杂逻辑

**完成定义（DoD）**
- 中间件链路顺序在代码中一眼可见，且与计划一致。
- checkpointer 在 agent 装配处可见且来源清晰。

## BLOCK-07 人工验证清单（工程师执行）
**目标**：由工程师手工验证，不要求 AI 编写测试脚本。  
**步骤（按序手工验）**
- [ ] 1. 同一 `thread_id` 连续多轮：确认会话上下文连续且摘要会更新（由 `SummarizationMiddleware` 或补丁逻辑触发）
- [ ] 2. 同一 `user_id` 新建 `thread_id`：确认能读到 user 中期画像
- [ ] 3. 临时性问题：确认不写入 mem0
- [ ] 4. 偏好/稳定事实：确认写入 mem0 且后续可检索到
- [ ] 5. 查看注入内容：顺序必须是“短期 -> 线程中期 -> user中期 -> mem0”
- [ ] 6. 查看摘要内容：若启用四段后处理，必须包含“目标/约束/进展/待办”

**完成定义（DoD）**
- 工程师确认以上 6 项均通过后，才能进入 BLOCK-08。

## BLOCK-08 回归与最终验收
**目标**：交付前统一收口，避免“能跑但不一致”。  
**步骤**
- [ ] 1. 核对配置项是否全部来自 `settings`/`.env`/`.env.example`
- [ ] 2. 核对是否存在整段写 mem0 的旧路径
- [ ] 3. 核对 `thread_id/user_id` 分工是否被破坏
- [ ] 4. 核对摘要主链路是否优先 `SummarizationMiddleware`
- [ ] 5. 输出变更说明：改了哪些文件、每块结果、剩余风险

**最终验收清单（全为必选）**
- [ ] 短期记忆落在 SQLite 线程态
- [ ] 中期总结可线程内滚动更新
- [ ] 中期画像可按 `user_id` 跨线程复用
- [ ] 长期记忆写入有准入，不是每轮都写
- [ ] 注入顺序固定：短期 -> 线程中期 -> user中期 -> mem0
- [ ] 临时注入消息会清理，不污染历史

## 2. 你后续下指令的标准模板
- “执行 BLOCK-01，不要做其他块。”
- “BLOCK-01 我验收通过，继续执行 BLOCK-02。”
- “回滚 BLOCK-03 到执行前状态，重新按计划做 BLOCK-03。”

## 3. 关于 frontmatter 里的 6 个 todo
- 这 6 个 todo 是计划元数据，用于执行者跟踪进度，不是让你逐条回答问题。
- 你不需要额外回复这 6 项；只需要按块下执行指令即可。
- 如果某一块出现实现分歧，再由我用 `AskQuestion` 单独向你提 1 个关键选择题。

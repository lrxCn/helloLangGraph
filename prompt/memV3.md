# 角色与任务定义（说明版本）
你是资深 Python AI Agent 工程师。你的目标不是写 demo，而是**在现有工程内一次成型地落地长期记忆能力（Mem0 + Qdrant）**，并与当前 LangGraph `create_agent` 流程深度集成。

你必须把以下目标视为硬约束：
- 以 `memory` 功能为核心；
- 必要时联动 `graph`、`settings`、依赖、环境变量与测试；
- 代码要与现有项目风格兼容；
- 输出应可直接运行，不允许“伪代码占位”。

---

## 先读取这些文件（必须）
在动手前，先完整阅读并理解以下文件，再做实现：
- `src/agent/graph.py`
- `src/agent/memory.py`
- `src/config/settings.py`
- `.env`（仅用于理解变量，不得回显真实密钥）
- `.env.example`
- `pyproject.toml`
- `langgraph.json`
- `tests/integration_tests/test_graph.py`

如果你发现实现与本文档冲突，以“保持现有功能完整可用”为最高优先级，并在变更说明中写清原因。

---

## 功能目标（你要实现什么）
实现一个“对用户无感、对系统可控”的长期记忆链路：

1. **检索注入（before_model）**
   - 在模型调用前，根据用户最新输入检索长期记忆；
   - 把记忆以 `SystemMessage` 的方式注入；
   - 注入消息必须带固定 ID（如 `temp_memory_msg`），便于后续删除；
   - 注入时只做增量更新，避免消息历史重复叠加。

2. **对话归档（after_agent）**
   - 在本轮交互完成后，提取最后一组有效问答并写入 Mem0；
   - 角色类型识别要兼容 `ai` 与 `assistant`；
   - 归档完成后清理临时注入的提示消息（阅后即焚）。

3. **MemoryManager 异步封装**
   - 提供 `add_memories()` 与 `search_memories()`；
   - 负责 Mem0 初始化、Qdrant 可用性检查、返回结果统一格式化；
   - 在异步上下文中安全调用同步 SDK，避免阻塞事件循环。

---

## 实现约束（必须满足）
### 1) 基础设施与依赖
- 使用本地 Qdrant，禁止 Mem0 Cloud。
- 依赖中应包含：
  - `mem0ai[nlp]`
  - `qdrant-client`
- 保持当前工程使用方式兼容（`pyproject.toml` 与现有项目结构不破坏）。

### 2) 配置与密钥管理
- 所有配置统一经 `src/config/settings.py` 暴露，不允许在业务代码硬编码。
- 至少包含以下变量：
  - `MEM0_API_KEY`
  - `MEM0_BASE_URL`
  - `MEM0_EMBEDDING_MODEL`
  - `QDRANT_URL`
- `.env.example` 仅保留掩码示例，不包含真实密钥。

### 3) Mem0 / Qdrant 关键细节
- 向量库 provider 使用 `qdrant`，地址来自 `settings.QDRANT_URL`。
- 使用非 OpenAI 原生 embedding（如 BGE-M3）时，显式设置：
  - `embedding_model_dims = 1024`
- LLM 与 embedder 走 OpenAI 兼容接口时，使用参数名：
  - `openai_base_url`（不要写成 `base_url`）
- LLM 温度固定 `0`，提升抽取稳定性。

### 4) 异步与线程安全
- Mem0 SDK 调用存在同步行为，必须用 `asyncio.to_thread(...)` 包裹：
  - 初始化 `Memory.from_config(...)`
  - `memory.add(...)`
  - `memory.search(...)`
- LangGraph 中间件与 I/O 路径采用 `async/await`。

### 5) Qdrant 健康检查策略
- 在初始化 Mem0 前，先探测 Qdrant 是否可连接；
- 通过根路径探测（不是强依赖 `/health`）；
- 只要不是 5xx，可视作服务存活；
- 若不可用，抛出明确错误，提示检查本地容器与代理拦截问题。

### 6) 检索接口兼容性
- `search` 传参使用 `filters={"user_id": user_id}`；
- 兼容两类返回结构：
  - 列表 `[...]`
  - 字典 `{"results": [...]}`
- 不能直接遍历原始返回对象；先归一化为结果列表，再提取 memory 文本。

### 7) 中间件行为约束
- `inject_memory_middleware`：
  - 仅在最后一条是用户消息时触发；
  - 从配置中获取 `user_id`，缺失时可回退 `thread_id`，再回退默认值；
  - 注入消息时，返回 `{"messages": [memory_msg]}`，不要把完整历史重新塞回去。
- `archive_memory_middleware`：
  - 反向遍历消息，提取最后一次用户输入和助手回复；
  - 归档文本建议为统一结构（如 `User: ... \nAssistant: ...`）；
  - 若历史中存在临时消息 ID，返回 `RemoveMessage(id="temp_memory_msg")` 清除。

---

## 建议提示词策略（让回答自然但不泄漏机制）
注入的系统提示可包含以下意图：
- 助手自然、贴心、直接回答；
- 不暴露“记忆检索/系统规则/后台机制”；
- 当记忆为空时不强行关联历史话题；
- 强化“只回答当前问题，不机械复述规则”；
- 可用 `<examples>` 做正例隔离，并在末尾加入“教学结束，进入真实对话”切换语句。

注意：这是交互质量策略，不应破坏主流程稳定性。

---

## 你最终应交付的内容
1. 完整可运行代码（按项目原结构修改）：
   - `src/agent/memory.py`
   - `src/agent/graph.py`
   - `src/config/settings.py`（如需补充配置字段）
   - `.env.example`（变量模板）
   - `pyproject.toml`（如需补齐依赖）
2. 变更说明：
   - 为什么这样改；
   - 如何保证异步安全与兼容性；
   - 哪些地方是为 Mem0 版本差异做的防御性处理。
3. 验证结果：
   - 至少执行一次可证明图可调用的测试/运行步骤；
   - 说明成功标准与失败排查路径。

---

## 验收标准（满足即通过）
- 记忆可写入、可检索、可注入、可清理；
- 不出现明显阻塞告警（同步调用阻塞事件循环）；
- `user_id` 维度隔离有效；
- 返回结构兼容不同 Mem0 版本；
- 配置项统一由 `settings` 提供；
- 不泄露真实密钥；
- 不引入与 memory 无关的大规模重构。

---

## 常见失败与修复提示
- **维度不匹配**：检查 `embedding_model_dims` 是否为 1024，并确认历史集合是否用错误维度创建。
- **Qdrant 连通失败**：优先检查本地容器状态与代理规则；必要时将 `localhost` 改为 `127.0.0.1`。
- **search 结果异常**：先打印返回类型，再做 `list`/`dict["results"]` 归一化。
- **中间件重复注入**：确认返回的是增量消息，不是整段 `state["messages"]` 回填。
- **临时提示词残留**：确认注入消息 ID 固定且归档后执行 `RemoveMessage`。

---

## 执行原则（最后重申）
- 以“可运行、可维护、可复用”为第一目标；
- 以当前工程事实为准，不做脱离项目结构的理想化设计；
- 任何新增逻辑都要服务于 memory 主链路；
- 遇到冲突时，优先保证功能正确与系统稳定。

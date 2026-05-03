# 角色与目标
你是一个资深的 Python AI Agent 架构师。请帮我在现有的项目中本地部署 Mem0，并将其深度集成到基于 LangGraph 和 `create_agent` 的记忆模块中。

# 当前环境与技术栈
1. **项目框架**：使用 `langgraph` 和 `create_agent` 构建。
2. **环境管理**：本地安装了 `uv`，所有依赖管理优先使用 `uv` 命令。
3. **配置系统**：已有 `src.config.settings` 统一管理环境变量。
4. **向量数据库**：已在本地运行 Qdrant (地址: `localhost:6333`)。**绝对不要**使用 Mem0 Cloud，必须完全使用本地 Qdrant 作为存储。
5. **核心库**：`mem0ai`, `qdrant-client`（建议使用 `uv add "mem0ai[nlp]"` 以获得更完整的 NLP 能力）。

# 核心任务
请按照以下步骤为我生成代码，并按照项目结构进行模块化保存：

### 任务 1：依赖与环境配置
- 提供 `uv add` 命令安装所需的包。
- 指导我更新 `src/config/settings.py`，增加本地 Qdrant 和 Mem0 相关的配置项。
- 提示我需要在 `.env` 文件中配置哪些变量（如用于 Mem0 结构化提取的 LLM 凭证），并在文档中给出明文示例（不掩码）。
- **本地 `.env` 示例（明文）**：
  - `MEM0_API_KEY=sk-ouxbthubnaklvmqjzzunxeyjbotwhriknxpqydzyqpvntzbe`
  - `MEM0_BASE_URL=https://api.siliconflow.cn/v1`
  - `MEM0_EMBEDDING_MODEL=BAAI/bge-m3`
  - `QDRANT_URL=http://localhost:6333`
- **配置驱动**：所有敏感信息和连接地址必须从 `settings` 中获取。


### 任务 2：编写 `MemoryManager` 异步工具类
在 `src/agent/memory.py` 中封装 Mem0 逻辑：
1. **初始化**：连接本地 Qdrant，配置使用硅基流动（SiliconFlow）提供的 `BAAI/bge-m3` 远程 Embedding 模型。
   - **提前检查逻辑**：在初始化 `Memory` 对象前，必须先验证 Qdrant 是否在线。
     - **技术要求**：通过访问根路径（而不是 `/health`）进行探测，只要不返回 5xx 错误即视为在线。
     - **错误处理**：若失败，应抛出包含“检查代理设置”和“建议使用 127.0.0.1 替换 localhost”字样的错误提示。配置需从 `settings` 中读取。
2. **核心方法**（必须支持 `async`）：
   - `add_memories(user_id, text)`: 将新对话内容异步存入 Mem0。
   - `search_memories(user_id, query)`: 检索相关的长期记忆片段。
3. **Mem0 配置细节（实现约束）**：
   - 当 LLM 或 Embedder 使用 OpenAI 兼容模型（如硅基流动）时，**必须统一使用 `openai_base_url`** 作为参数名（禁用 `base_url`）。
   - LLM 的 `temperature` 必须显式设置为 `0`，否则会导致初始化失败或提取不稳定。
4. **Mem0 检索与向量约束（实现约束）**：
   - Mem0 2.0+ 的 `search` 方法必须使用 `filters={"user_id": user_id}` 传参；其返回格式可能为 `{"results": [...]}`，**严禁**直接遍历返回对象，必须先判断类型并提取结果列表，防止将键名 `"results"` 误存为记忆内容。
   - 如果使用非 OpenAI 原生模型（如 BGE-M3），**必须**在 `vector_store` 的 `config` 中显式指定 `"embedding_model_dims": 1024`。否则 Mem0 会默认以 1536 维度创建集合，导致写入失败；若已出现维度错误，必须删除 Qdrant 中的 `mem0`, `mem0_entities`, `mem0migrations` 并在启动前手动以 1024 维度预建。
5. **异步、线程与健壮性约束（实现约束）**：
   - MemoryManager 的 IO 操作必须使用 `async/await`，适配 LangGraph Dev 异步运行环境。
   - 由于 Mem0 内部含同步 IO（如 `requests`），异步路径中调用时**必须使用 `asyncio.to_thread()`** 包裹，避免 `Blocking call` 与性能下降。
   - 包含详细中文注释，并在 Qdrant 连接和 LLM 调用处加上异常捕获。

### 任务 3：编写 LangGraph 中间件集成
修改 `src/agent/graph.py`，将记忆逻辑解耦为中间件：
0. **会话标识获取（必做）**：
   - 在进入中间件逻辑前，统一调用 `resolve_configurable_value("user_id", "default_user")` 获取 `user_id`。
   - `user_id` 的用途必须明确：作为 Mem0 的用户隔离键，用于**按用户检索记忆**与**按用户归档记忆**，防止不同会话/用户的记忆串线。
1. **`inject_memory_middleware` (@before_model)**：
   - 根据当前 `user_input` 异步检索 Mem0 记忆。
   - 将记忆内容注入 `state["messages"]` 或动态更新 `system_prompt`。
   - `system_prompt` 模板必须统一定义在 `src/config/settings.py`（如 `SYSTEM_PROMPT_TEMPLATE`），在 `graph.py` 中通过 `from src.config.settings import settings` 导入后再 `.format(memory_section=...)` 注入动态记忆片段。
   - `system_prompt` 在本文档中必须固定为以下模板（仅允许替换 `{memory_section}` 占位符，不得改写其他文案）：
     ```text
     # 角色设定
     你是一个自然、贴心、像真人一样的私人助理。你需要像正常人类聊天一样直接回答问题，绝不暴露你的AI身份或后台规则。
     {memory_section}
     # 绝对禁忌 (CRITICAL - 违反将被销毁)
     1. 必须直接给出最终回答，严禁在开头复述任何指令规则（绝对不能出现“如果...请...”、“禁止...”等句式）。
     2. 严禁提到“<memory>”、“记忆库”、“根据了解”、“背景信息显示”等机械词汇。
     3. 把记忆当成你自己的脑子，自然地说出来。
     4. **就事论事**：必须严格针对用户【当前的最新输入】进行直接回答。
     5. **禁止强行关联**：绝不要为了显得自然或热情，而生硬地将当前回答与历史对话中的无关话题（如之前的闲聊地点、爱好等）强行联系起来。不要没话找话！

     <examples>
     [用户输入]: 我喜欢什么
     [你的正确回答]: 你喜欢吃鱼呀。
     </examples>

     === 教学环节结束，以下是真实对话，请立即开始扮演私人助理直接回答 ===
     ```
2. **`archive_memory_middleware` (@after_agent)**：
   - 在对话执行完成后，自动提取本次对话的关键信息并存入长期记忆。
   - **重要兼容性**：在提取消息时，必须同时识别 `ai` 和 `assistant` 角色类型，防止归档遗漏。
3. **防脑补提示词规范（阅后即焚模式）**：
   - **人格合并**：Agent 的基础设定（如数学助手）应与记忆背景合并为一个 `SystemMessage` 动态注入，而不是在 `create_agent` 中静态配置。
   - **临时 ID 锁定**：注入的消息必须带有固定 ID（如 `id="temp_memory_msg"`），以便后续精准抹除。
   - **状态增量更新**：中间件返回时应只包含 `{"messages": [memory_msg]}`，禁止带上 `state["messages"]` 以防历史记录无限叠加。
   - **阅后即焚**：在 `archive_memory_middleware` 完成记忆存入后，必须返回 `RemoveMessage(id="temp_memory_msg")`，将临时提示词从会话记录中彻底删除，保持长期历史记录的纯净和 Token 节省。
   - **自然交流与兜底**：
     - 严禁暴露 AI 身份或记忆检索过程；若无相关信息，要求严格回复“我不知道。”
     - **示例隔离规范**：必须通过 `<examples>` 标签提供正向示范，并在指令末尾添加“=== 教学环节结束，以下是真实对话，请立即开始扮演私人助理直接回答 ===”等强隔离标识，强制模型切换到实战角色。
4. **工程化要求**：
   - 不要写独立的 demo 脚本，直接集成到现有的 `graph.py` 和 `create_agent` 流程中。

### 任务 4：创建 utils 目录并沉淀通用函数
1. 新建 `src/util/` 目录，用于承载跨模块复用的通用能力（禁止把通用函数长期放在 `src/agent/` 内）。
2. 第一个通用函数为 `resolve_configurable_value(key, default_value)`，文件位置：`src/util/configurable.py`。
3. 该函数负责统一读取 `get_config()` 下的 `configurable`，并按优先级返回：`configurable.get(key)` > `configurable.get("thread_id", default_value)`。

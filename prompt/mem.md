# 角色与目标
你是一个资深的 Python AI Agent 架构师。请帮我在现有的项目中本地部署 Mem0，并将其深度集成到基于 LangGraph 和 `create_agent` 的记忆模块中。

# 当前环境与技术栈
1. **项目框架**：使用 `langgraph` 和 `create_agent` 构建。
2. **环境管理**：本地安装了 `uv`，所有依赖管理优先使用 `uv` 命令。
3. **配置系统**：已有 `src.config.settings` 统一管理环境变量。
4. **向量数据库**：已在本地运行 Qdrant (地址: `localhost:6333`)。**绝对不要**使用 Mem0 Cloud，必须完全使用本地 Qdrant 作为存储。
5. **核心库**：`mem0ai`, `qdrant-client`。

# 核心任务
请按照以下步骤为我生成代码，并按照项目结构进行模块化保存：

### 任务 1：依赖与环境配置
- 提供 `uv add` 命令安装所需的包。
- 指导我更新 `src/config/settings.py`，增加本地 Qdrant 和 Mem0 相关的配置项。
- 提示我需要在 `.env` 文件中配置哪些变量（如用于 Mem0 结构化提取的 LLM 凭证），并用掩码同步到.env.example。

### 任务 2：编写 `MemoryManager` 异步工具类
在 `src/agent/memory.py` 中封装 Mem0 逻辑：
1. **初始化**：连接本地 Qdrant，配置使用硅基流动（SiliconFlow）提供的 `BAAI/bge-m3` 远程 Embedding 模型。
   - **提前检查逻辑**：在初始化 `Memory` 对象前，必须先验证 Qdrant 是否在线。
     - **技术要求**：通过访问根路径（而不是 `/health`）进行探测，只要不返回 5xx 错误即视为在线。
     - **错误处理**：若失败，应抛出包含“检查代理设置”和“建议使用 127.0.0.1 替换 localhost”字样的错误提示。配置需从 `settings` 中读取。
2. **核心方法**（必须支持 `async`）：
   - `add_memories(user_id, text)`: 将新对话内容异步存入 Mem0。
   - `search_memories(user_id, query)`: 检索相关的长期记忆片段。

### 任务 3：编写 LangGraph 中间件集成
修改 `src/agent/graph.py`，将记忆逻辑解耦为中间件：
0. **会话标识获取（必做）**：
   - 在进入中间件逻辑前，统一调用 `resolve_configurable_value("user_id", "default_user")` 获取 `user_id`。
   - `user_id` 的用途必须明确：作为 Mem0 的用户隔离键，用于**按用户检索记忆**与**按用户归档记忆**，防止不同会话/用户的记忆串线。
1. **`inject_memory_middleware` (@before_model)**：
   - 根据当前 `user_input` 异步检索 Mem0 记忆。
   - 将记忆内容注入 `state["messages"]` 或动态更新 `system_prompt`。
2. **`archive_memory_middleware` (@after_agent)**：
   - 在对话执行完成后，自动提取本次对话的关键信息并存入长期记忆。
   - **重要兼容性**：在提取消息时，必须同时识别 `ai` 和 `assistant` 角色类型，防止归档遗漏。

### 任务 4：创建 utils 目录并沉淀通用函数
1. 新建 `src/util/` 目录，用于承载跨模块复用的通用能力（禁止把通用函数长期放在 `src/agent/` 内）。
2. 第一个通用函数为 `resolve_configurable_value(key, default_value)`，文件位置：`src/util/configurable.py`。
3. 该函数负责统一读取 `get_config()` 下的 `configurable`，并按优先级返回：`configurable.get(key)` > `configurable.get("thread_id", default_value)`。

# 代码规范与要求
- **异步化**：由于运行在 LangGraph Dev 环境，所有中间件和 IO 操作必须使用 `async/await`。
- **配置读取规范（基于当前实现）**：配置读取必须封装为通用函数并放在 util 目录（如 `src/util/configurable.py` 中的 `resolve_configurable_value(key, default_value)`），调用时传入字符串参数（示例：`resolve_configurable_value("user_id", "default_user")`）。函数内部通过 `get_config()` 读取 `configurable = config.get("configurable", {})`，并遵循优先级：`configurable.get(key)` > `configurable.get("thread_id", default_value)`。
- **Mem0 配置细节**：当 LLM 或 Embedder 使用 OpenAI 兼容模型（如硅基流动）时，**必须统一使用 `openai_base_url`** 作为参数名（禁用 `base_url`），且 LLM 的 `temperature` 必须显式设置为 `0`，否则会导致初始化失败或提取不稳定。
- **Search 接口规范**：Mem0 2.0+ 的 `search` 方法必须使用 `filters={"user_id": user_id}` 传参。同时注意其返回格式可能为 `{"results": [...]}`，**严禁**直接遍历返回对象，必须先判断类型并提取其中的结果列表，防止将键名 `"results"` 误存为记忆内容。
- **向量维度冲突与锁定**：如果使用非 OpenAI 原生模型（如 BGE-M3），**必须**在 `vector_store` 的 `config` 中显式指定 `"embedding_model_dims": 1024`。否则 Mem0 会默认以 1536 维度创建集合，导致写入失败。如果已经报维度错误，必须删除 Qdrant 中的 `mem0`, `mem0_entities`, `mem0migrations` 并在启动前手动以 1024 维度预建。
- **线程安全与非阻塞**：由于 Mem0 内部使用的是同步 IO（如 `requests`），在 LangGraph 的异步中间件中调用时，**必须使用 `asyncio.to_thread()`** 进行包裹，否则会触发 `Blocking call` 报错并降低系统性能。
- **依赖建议**：为了获得更好的记忆提取准确度并消除警告，建议使用 `uv add "mem0ai[nlp]"` 安装包含 NLP 支持的完整版本。
- **配置驱动**：所有敏感信息和连接地址必须从 `settings` 中获取。
- **健壮性**：包含详细的中文注释，并在 Qdrant 连接和 LLM 调用处加上异常捕获。
- **网络建议**：在 `.env` 配置中，建议优先使用 `127.0.0.1` 替换 `localhost` 以规避系统解析风险。
- **工程化**：不要写独立的 demo 脚本，直接集成到现有的 `graph.py` 和 `create_agent` 流程中。
- **防脑补提示词规范（阅后即焚模式）**：
  - **人格合并**：Agent 的基础设定（如数学助手）应与记忆背景合并为一个 `SystemMessage` 动态注入，而不是在 `create_agent` 中静态配置。
  - **临时 ID 锁定**：注入的消息必须带有固定 ID（如 `id="temp_memory_msg"`），以便后续精准抹除。
  - **状态增量更新**：中间件返回时应只包含 `{"messages": [memory_msg]}`，禁止带上 `state["messages"]` 以防历史记录无限叠加。
  - **阅后即焚**：在 `archive_memory_middleware` 完成记忆存入后，必须返回 `RemoveMessage(id="temp_memory_msg")`，将临时提示词从会话记录中彻底删除，保持长期历史记录的纯净和 Token 节省。
  - **自然交流与兜底**：
    - 严禁暴露 AI 身份或记忆检索过程；若无相关信息，要求严格回复“我不知道。”
    - **示例隔离规范**：必须通过 `<examples>` 标签提供正向示范，并在指令末尾添加“=== 教学环节结束，以下是真实对话，请立即开始扮演私人助理直接回答 ===”等强隔离标识，强制模型切换到实战角色。
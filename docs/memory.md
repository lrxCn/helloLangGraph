# 记忆系统执行规范（确定性分块版）

> 文档目标：可被多个 AI 以 `@块` 方式独立执行，且输出高度一致。  
> 适用范围：`LangGraph + create_agent + Mem0 + Qdrant`。  
> 约束级别：本文件为“强约束协议”，禁止自由发挥。

---

## BLOCK-00 总则（只读）

**唯一职责**：定义全局原则，避免实现漂移。

### 固定规则

1. 所有数值阈值必须来自 `settings`，禁止硬编码。  
2. 本文中 `N` 仅指 `SHORT_TERM_WINDOW_TURNS`。  
3. “摘要触发轮次”不再使用第二个独立 N，统一为 `N * MID_TERM_TRIGGER_MULTIPLIER`。  
4. 每个块只做一件事，块间通过“输入/输出契约”衔接。  
5. 如果块内出现“可选/建议/例如”等弹性词，视为文档缺陷，必须改为固定值。

---

## BLOCK-01 配置字典（唯一参数源）

**唯一职责**：定义记忆相关配置键与约束。

### 必须存在的 `settings` 字段

- `SHORT_TERM_WINDOW_TURNS: int`  
  - 含义：短期窗口轮数（N）  
  - 约束：`>= 2`
- `MID_TERM_TRIGGER_MULTIPLIER: int`  
  - 含义：中期摘要触发倍数（K）  
  - 约束：`>= 1`
- `MODEL_CONTEXT_WINDOW: int`  
  - 含义：模型上下文窗口上限（token）  
  - 约束：`>= 1024`
- `SUMMARY_TRIGGER_CONTEXT_RATIO: float`  
  - 含义：按上下文窗口触发摘要的比例  
  - 约束：读取后强制夹紧到 `[0.20, 0.90]`
- `MID_TERM_SUMMARY_MAX_CHARS: int`  
  - 含义：中期摘要最大字符数  
  - 约束：`>= 200`
- `MEM0_SEARCH_TOP_K: int`  
  - 含义：长期记忆检索条数  
  - 约束：`>= 1`

### 固定派生公式

1. `N = SHORT_TERM_WINDOW_TURNS`  
2. `K = MID_TERM_TRIGGER_MULTIPLIER`  
3. `MID_TERM_TRIGGER_TURNS = N * K`  
4. `R = clamp(SUMMARY_TRIGGER_CONTEXT_RATIO, 0.20, 0.90)`  
5. `SUMMARY_TRIGGER_TOKEN_LIMIT = floor(MODEL_CONTEXT_WINDOW * R)`

> 说明：`@docs/memory.md:46` 和 `@docs/memory.md:48` 使用同一个 N。  
> 说明：`@docs/memory.md:55` 以前的“另一个 N”已取消，统一为 `N*K` 或 token 阈值触发。

---

## BLOCK-02 窗口与摘要触发（确定性策略）

**唯一职责**：给出唯一、可复现的触发规则。

### 输入

- `turn_count`（当前线程累计轮数）
- `current_prompt_tokens`（当前拼装后的 prompt token 数）
- BLOCK-01 的配置字段

### 输出

- `need_update_summary: bool`

### 固定判定逻辑

按以下顺序执行，命中任意一条即触发：

1. **轮次触发**：`turn_count % MID_TERM_TRIGGER_TURNS == 0`
2. **token 触发**：`current_prompt_tokens >= SUMMARY_TRIGGER_TOKEN_LIMIT`

若都不命中，返回 `False`。

### 关于“模型上下文窗口能否拿到”

采用固定双通道策略：

1. **优先**：若运行时可读取模型元信息中的 context window，则使用该值。  
2. **回退**：读取失败时使用 `settings.MODEL_CONTEXT_WINDOW`。  

无论来源如何，最终都走 BLOCK-01 的 `SUMMARY_TRIGGER_TOKEN_LIMIT` 公式。

---

## BLOCK-03 短期记忆（会话窗口）

**唯一职责**：维护最近窗口消息，不涉及长期存储。

### 输入

- 当前线程 `messages`
- `N = SHORT_TERM_WINDOW_TURNS`

### 输出

- `short_term_messages`（固定为最近 `N` 轮 user+assistant 对）

### 固定规则

1. “一轮”定义为一个 `user` 消息及其对应 `assistant/ai` 消息。  
2. 仅截取最近 `N` 轮，禁止超窗。  
3. 工具消息只保留与最近 `N` 轮相关的片段。  
4. 短期记忆只存在于线程态（checkpointer scope），禁止写入 mem0。

---

## BLOCK-04 中期记忆（线程摘要）

**唯一职责**：把长会话压缩为稳定摘要。

### 输入

- `running_summary`（旧摘要）
- `short_term_messages`
- 触发信号（BLOCK-02）

### 输出

- 新 `running_summary`

### 固定格式（摘要模板）

摘要必须按以下 4 段输出，缺失段落也保留标题：

1. `目标`
2. `约束`
3. `进展`
4. `待办`

### 固定约束

1. 仅当 `need_update_summary=True` 时更新。  
2. 更新方式固定：`旧摘要 + 最近窗口关键信息 -> 新摘要`。  
3. 长度不超过 `MID_TERM_SUMMARY_MAX_CHARS`。  
4. 中期摘要属于线程内记忆，不直接写入 mem0。

---

## BLOCK-05 长期记忆（Mem0 写入）

**唯一职责**：以准入制写入跨会话记忆。

### 输入

- 本轮对话关键信息（用户 + 助手）
- `user_id`

### 输出

- Mem0 写入动作（或跳过）

### 固定规则

1. 必须先做准入判断，未通过则不写入。  
2. 写入时必须带 `user_id`。  
3. 长期库只存可复用信息，禁止把整轮对话原样入库。  
4. 对于同类偏好，采用最新值覆盖策略（LWW）。

---

## BLOCK-06 Mem0 检索（确定性解析）

**唯一职责**：稳定检索并规避返回格式歧义。

### 固定调用方式

1. `search(..., filters={"user_id": user_id})`  
2. 返回值解析顺序固定：
   - 若是 `dict`：仅取 `result["results"]` 且必须是 `list`
   - 若是 `list`：直接使用
   - 其余类型：视为空

### 明确禁令

- 严禁直接遍历原始返回对象（防止把键名 `"results"` 当内容）。  
- 严禁无 `user_id` 过滤检索。

---

## BLOCK-07 Qdrant 与向量维度（硬约束）

**唯一职责**：保证本地向量存储稳定。

### 固定规则

1. 只允许本地 Qdrant，禁止 Mem0 Cloud。  
2. `vector_store.config.embedding_model_dims` 必须显式为 `1024`（`BAAI/bge-m3`）。  
3. 若发生维度冲突，按固定恢复流程：
   - 删除集合：`mem0`、`mem0_entities`、`mem0migrations`
   - 以 `1024` 维重新初始化

### 连通性检查

1. 初始化 Mem0 前，必须请求 Qdrant 根路径（不是 `/health`）。  
2. 只要不是 5xx 即判定在线。  
3. 失败报错文案必须包含：
   - “检查代理设置”
   - “建议使用 127.0.0.1 替换 localhost”

---

## BLOCK-08 中间件编排（固定顺序）

**唯一职责**：统一 graph 执行链路，保证一致性。

### 固定顺序

1. `before_model`：注入短期 + 中期 + 长期记忆（按此顺序）  
2. `model/tools`：推理与工具执行  
3. `after_agent`：归档候选长期记忆 + 清理临时注入消息

### 固定实现点

1. `user_id` 必须先通过 `resolve_configurable_value("user_id", "default_user")` 获取。  
2. 临时注入消息必须固定 `id="temp_memory_msg"`。  
3. 注入更新必须返回增量：`{"messages": [memory_msg]}`。  
4. 归档后必须返回 `RemoveMessage(id="temp_memory_msg")`。

---

## BLOCK-09 提示词注入（固定模板）

**唯一职责**：定义唯一 system prompt 来源与注入方式。

### 固定规则

1. 模板只允许放在 `settings.SYSTEM_PROMPT_TEMPLATE`。  
2. 在 graph 中只允许 `.format(memory_section=...)` 动态注入。  
3. 禁止在 `create_agent` 里设置静态 `system_prompt`。  
4. 无相关信息时兜底固定为：`我不知道。`

---

## BLOCK-10 工程拆块契约（给多 AI 并行执行）

**唯一职责**：每块可独立派发，不需要整文上下文。

### 可派发块

- `@BLOCK-01`：只改配置与参数公式  
- `@BLOCK-02`：只改触发判定函数  
- `@BLOCK-03`：只改短期窗口截断  
- `@BLOCK-04`：只改中期摘要更新  
- `@BLOCK-05`：只改长期写入准入  
- `@BLOCK-06`：只改 Mem0 检索解析  
- `@BLOCK-07`：只改 Qdrant 探测和维度策略  
- `@BLOCK-08`：只改 middleware 顺序与消息清理  
- `@BLOCK-09`：只改 prompt 模板注入来源

### 每块统一交付格式

1. 修改文件列表  
2. 固定输入/输出  
3. 判定公式（如有）  
4. 最小测试点（1-3 条）

---

## BLOCK-11 最小配置示例（明文）

**唯一职责**：给出一次可运行的 `.env` 参考值。

```env
MEM0_API_KEY=sk-ouxbthubnaklvmqjzzunxeyjbotwhriknxpqydzyqpvntzbe
MEM0_BASE_URL=https://api.siliconflow.cn/v1
MEM0_EMBEDDING_MODEL=BAAI/bge-m3
QDRANT_URL=http://localhost:6333
SHORT_TERM_WINDOW_TURNS=4
MID_TERM_TRIGGER_MULTIPLIER=2
MODEL_CONTEXT_WINDOW=32768
SUMMARY_TRIGGER_CONTEXT_RATIO=0.5
MID_TERM_SUMMARY_MAX_CHARS=300
MEM0_SEARCH_TOP_K=5
```

---

## BLOCK-12 验收清单（必须全过）

**唯一职责**：提供最终一致性验收标准。

- [ ] `N` 只有一个定义：`SHORT_TERM_WINDOW_TURNS`  
- [ ] 摘要轮次触发使用 `N*K`，不存在第二个独立 N  
- [ ] token 触发阈值来源于 `context_window * ratio`，且 ratio 已夹紧到 20%-90%  
- [ ] `search` 使用 `filters={"user_id": user_id}`  
- [ ] 检索结果按 `dict["results"]`/`list` 两路解析  
- [ ] Qdrant 预检查走根路径，失败报错文案满足关键词要求  
- [ ] 向量维度固定 1024  
- [ ] 中间件注入与清理顺序满足 BLOCK-08  
- [ ] 全部阈值来自 `settings`，无硬编码

---

## BLOCK-13 一句话执行指令

先固化参数，再固化公式，再固化流程；禁止在实现阶段引入新术语和新阈值。

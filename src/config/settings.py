import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

SYSTEM_PROMPT_TEMPLATE = """# 角色设定
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
"""


class Settings:
    def __init__(self):
        self.SYSTEM_PROMPT_TEMPLATE = SYSTEM_PROMPT_TEMPLATE
        self.LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        self.OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
        self.OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME")
        self.TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
        self.LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "true")
        
        # Mem0 & Qdrant 配置
        self.MEM0_API_KEY = os.getenv("MEM0_API_KEY")
        self.MEM0_BASE_URL = os.getenv("MEM0_BASE_URL")
        self.MEM0_EMBEDDING_MODEL = os.getenv("MEM0_EMBEDDING_MODEL", "BAAI/bge-m3")
        self.QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")


settings = Settings()

import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


class Settings:
    def __init__(self):
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

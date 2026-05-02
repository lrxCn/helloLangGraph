import asyncio
import logging
from typing import List, Dict, Any, Optional
import httpx
from mem0 import Memory
from src.config.settings import settings

logger = logging.getLogger(__name__)

class MemoryManager:
    def __init__(self):
        # Mem0 配置：强制使用本地 Qdrant 和硅基流动 Embedding
        self.config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "url": settings.QDRANT_URL,
                    "embedding_model_dims": 1024,
                }
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "api_key": settings.MEM0_API_KEY,
                    "openai_base_url": settings.MEM0_BASE_URL,
                    "model": settings.OPENAI_MODEL_NAME,
                    "temperature": 0,
                }
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": settings.MEM0_EMBEDDING_MODEL,
                    "api_key": settings.MEM0_API_KEY,
                    "openai_base_url": settings.MEM0_BASE_URL,
                }
            }
        }
        self.memory: Optional[Memory] = None

    async def initialize(self):
        """初始化 Mem0，包含 Qdrant 健康检查"""
        # 1. 提前检查 Qdrant 是否在线 (根据用户要求，不在线则中断)
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                # 尝试访问 Qdrant 根路径 (不带 /health，因为有些版本不支持)
                health_url = settings.QDRANT_URL
                response = await client.get(health_url, timeout=5.0)
                # 只要能连上（状态码小于 500），就认为服务是存活的
                if response.status_code >= 500:
                    raise Exception(f"Qdrant 服务端异常，状态码: {response.status_code}")
        except Exception as e:
            error_msg = f"❌ Qdrant 连接失败 (地址: {settings.QDRANT_URL})。请检查：1.OrbStack 是否运行 2.是否开启了代理拦截 localhost"
            logger.error(error_msg)
            # 中断任务并提示用户
            raise RuntimeError(error_msg) from e

        # 2. 初始化 Mem0 实例
        try:
            # 关键修复：使用 to_thread 防止同步初始化阻塞异步循环
            self.memory = await asyncio.to_thread(Memory.from_config, self.config)
            logger.info("✅ Mem0 长期记忆模块初始化成功 (Qdrant 已在线)")
        except Exception as e:
            logger.error(f"❌ Mem0 内部初始化失败: {str(e)}")
            raise

    async def add_memories(self, text: str, user_id: str):
        """将对话存入 Mem0 长期记忆 (线程安全)"""
        if not self.memory:
            await self.initialize()
        # 关键修复：使用 to_thread 包裹同步的 add 方法
        return await asyncio.to_thread(self.memory.add, text, user_id=user_id)

    async def search_memories(self, query: str, user_id: str) -> str:
        """根据查询内容检索相关的长期记忆 (线程安全)"""
        if not self.memory:
            await self.initialize()
        
        # 关键修复：Mem0 有些版本返回列表，有些返回字典 {"results": [...]}
        raw_output = await asyncio.to_thread(self.memory.search, query, filters={"user_id": user_id})
        
        # 提取真正的结果列表
        results = []
        if isinstance(raw_output, list):
            results = raw_output
        elif isinstance(raw_output, dict) and "results" in raw_output:
            results = raw_output["results"]
            
        if not results:
            return ""
        
        # 格式化记忆片段为文本字符串
        mem_strings = []
        for res in results:
            if isinstance(res, dict) and "memory" in res:
                mem_strings.append(res["memory"])
            elif hasattr(res, "memory"):
                mem_strings.append(res.memory)
            else:
                mem_strings.append(str(res))
                
        return "\n".join([f"- {m}" for m in mem_strings])

# 导出单例供中间件调用
memory_manager = MemoryManager()

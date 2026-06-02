"""
建图谱脚本：用 labor_law.txt 构建 LightRAG 知识图谱，存到 lightrag_store。
建好后，网页应用只需加载、查询，不用重建（部署时把 lightrag_store 一起带上即可）。
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
import asyncio
import numpy as np
from openai import AsyncOpenAI
from lightrag import LightRAG
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc
from lightrag.kg.shared_storage import initialize_pipeline_status

from dotenv import load_dotenv
load_dotenv()
KEY = os.getenv("SILICONFLOW_KEY")
BASE = "https://api.siliconflow.com/v1"
WORKDIR = "./lightrag_store"

async def llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
    return await openai_complete_if_cache(
        "deepseek-ai/DeepSeek-V3", prompt,
        system_prompt=system_prompt, history_messages=history_messages,
        api_key=KEY, base_url=BASE, **kwargs,
    )

_embed_client = AsyncOpenAI(api_key=KEY, base_url=BASE)
async def embed_func(texts):
    resp = await _embed_client.embeddings.create(
        model="Qwen/Qwen3-Embedding-0.6B", input=texts, encoding_format="float",
    )
    return np.array([d.embedding for d in resp.data], dtype=np.float32)

async def main():
    rag = LightRAG(
        working_dir=WORKDIR,
        llm_model_func=llm_func,
        embedding_func=EmbeddingFunc(embedding_dim=1024, max_token_size=8192, func=embed_func),
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    print("开始构建知识图谱（数据较多，请耐心等几分钟）...")
    with open("labor_law.txt", "r", encoding="utf-8") as f:
        await rag.ainsert(f.read())
    print("✅ 知识图谱构建完成！已存入 lightrag_store/")

asyncio.run(main())

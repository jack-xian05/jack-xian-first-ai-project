"""
LightRAG 交互查询（复用已建好的知识图谱，不重新建图，快又省）
对比4种模式，你能直观感受 naive(普通RAG) 和 hybrid(图谱) 的差别。
运行：py lightrag_query.py
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
import asyncio
import numpy as np
from openai import AsyncOpenAI
from lightrag import LightRAG, QueryParam
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
    print("✅ 知识图谱已加载！输入问题（quit退出）")
    print("   提示：试试需要'串联'的问题，比如'试用期辞职和正式辞职有什么不同？'\n")

    while True:
        q = input("你：").strip()
        if q.lower() in ("quit", "exit", "退出"):
            print("再见！")
            break
        if not q:
            continue
        # 用 hybrid 模式（图谱+向量，最强）
        ans = await rag.aquery(q, param=QueryParam(mode="hybrid"))
        print(f"\nAI（知识图谱）：\n{ans}\n" + "-" * 50)

asyncio.run(main())

"""
LightRAG 入门：用知识图谱方式做 RAG
和你之前的普通RAG对比：
  普通RAG：把文档切块→向量化→找相似块
  LightRAG：把文档→LLM抽取实体和关系→建知识图谱→能顺关系链检索

注意：第一次运行会调用LLM抽取实体，比普通RAG慢、耗额度，这是图谱RAG的代价。
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"   # 关掉base64，避开解码不兼容
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
WORKDIR = "./lightrag_store"   # 图谱数据存这里

os.makedirs(WORKDIR, exist_ok=True)

# ===== 告诉 LightRAG 怎么调用大模型 =====
async def llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
    return await openai_complete_if_cache(
        "deepseek-ai/DeepSeek-V3", prompt,
        system_prompt=system_prompt, history_messages=history_messages,
        api_key=KEY, base_url=BASE, **kwargs,
    )

# ===== 自己写向量化函数（绕过LightRAG的openai_embed，它会硬塞dimensions=1536害死Qwen）=====
_embed_client = AsyncOpenAI(api_key=KEY, base_url=BASE)
async def embed_func(texts):
    resp = await _embed_client.embeddings.create(
        model="Qwen/Qwen3-Embedding-0.6B",
        input=texts,
        encoding_format="float",   # 用float，不用base64
    )                              # 注意：不传 dimensions，Qwen原生1024维
    return np.array([d.embedding for d in resp.data], dtype=np.float32)

async def main():
    rag = LightRAG(
        working_dir=WORKDIR,
        llm_model_func=llm_func,
        embedding_batch_num=1,           # 关键修复：一条一条发，避开硅基流动批处理的坑
        embedding_func=EmbeddingFunc(
            embedding_dim=1024,          # Qwen3-Embedding-0.6B 的维度
            max_token_size=8192,
            func=embed_func,
        ),
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()

    # ===== 第①步：插入文档，建知识图谱（慢，要调LLM抽实体）=====
    print("① 正在读取劳动法文档并构建知识图谱（这步慢，耐心等）...")
    with open("labor_law.txt", "r", encoding="utf-8") as f:
        await rag.ainsert(f.read())
    print("   知识图谱构建完成！\n")

    # ===== 第②步：用不同模式提问 =====
    question = "试用期和经济补偿之间有什么关系？工作没多久被辞退能拿补偿吗？"
    print(f"问题：{question}\n")

    # hybrid 模式：图谱关系 + 向量，最强
    print("【LightRAG hybrid 模式回答】")
    answer = await rag.aquery(question, param=QueryParam(mode="hybrid"))
    print(answer)

asyncio.run(main())

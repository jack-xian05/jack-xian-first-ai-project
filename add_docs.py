import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
import asyncio, numpy as np
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
        "deepseek-ai/DeepSeek-V3.1", prompt, system_prompt=system_prompt,
        history_messages=history_messages, api_key=KEY, base_url=BASE, **kwargs,
    )

_embed_client = AsyncOpenAI(api_key=KEY, base_url=BASE)
async def embed_func(texts):
    resp = await _embed_client.embeddings.create(
        model="Qwen/Qwen3-Embedding-0.6B", input=texts, encoding_format="float",
    )
    return np.array([d.embedding for d in resp.data], dtype=np.float32)

async def main():
    rag = LightRAG(
        working_dir=WORKDIR, llm_model_func=llm_func,
        embedding_func=EmbeddingFunc(embedding_dim=1024, max_token_size=8192, func=embed_func),
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    with open("labor_law_extra.txt", "r", encoding="utf-8") as f:
        content = f.read()
    print("开始插入新法规文档...")
    await rag.ainsert(content)
    print("新文档插入完成！")

asyncio.run(main())

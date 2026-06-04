"""
公共 LLM / Embedding 工具 —— 之前这些函数在 4 个文件里复制粘贴，现在统一一份。
额外加了【指数退避重试】：网络抖动、限流(429)、超时时自动重试，不再一遇错就崩。
"""
import os
os.environ.setdefault("EMBEDDING_USE_BASE64", "false")  # 关 base64，避开解码不兼容

import asyncio
import functools
import numpy as np
from openai import AsyncOpenAI, OpenAI, APIError, APITimeoutError, APIConnectionError, RateLimitError

import config

# 可重试的瞬时错误：限流、超时、连接问题
_RETRIABLE = (RateLimitError, APITimeoutError, APIConnectionError)


def _async_retry(func):
    """异步函数指数退避重试装饰器"""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        last_err = None
        for attempt in range(config.MAX_RETRIES):
            try:
                return await func(*args, **kwargs)
            except _RETRIABLE as e:
                last_err = e
                delay = config.RETRY_BASE_DELAY * (2 ** attempt)
                print(f"⚠️ API 调用失败({type(e).__name__})，{delay:.0f}s 后第 {attempt + 1} 次重试...")
                await asyncio.sleep(delay)
        raise last_err
    return wrapper


def _sync_retry(func):
    """同步函数指数退避重试装饰器"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        import time
        last_err = None
        for attempt in range(config.MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except _RETRIABLE as e:
                last_err = e
                delay = config.RETRY_BASE_DELAY * (2 ** attempt)
                print(f"⚠️ API 调用失败({type(e).__name__})，{delay:.0f}s 后第 {attempt + 1} 次重试...")
                time.sleep(delay)
        raise last_err
    return wrapper


# ===== 异步客户端（LightRAG 用）=====
_async_client = AsyncOpenAI(api_key=config.SILICONFLOW_KEY, base_url=config.BASE_URL)
# ===== 同步客户端（合同分析 / 图片识别用）=====
sync_client = OpenAI(api_key=config.SILICONFLOW_KEY, base_url=config.BASE_URL)


@_async_retry
async def llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
    """LightRAG 的生成模型函数（查询/回答用 LLM_MODEL）"""
    from lightrag.llm.openai import openai_complete_if_cache
    return await openai_complete_if_cache(
        config.LLM_MODEL, prompt,
        system_prompt=system_prompt, history_messages=history_messages,
        api_key=config.SILICONFLOW_KEY, base_url=config.BASE_URL, **kwargs,
    )


@_async_retry
async def embed_func(texts):
    """向量化函数（不传 dimensions，保留 Qwen 原生 1024 维）"""
    resp = await _async_client.embeddings.create(
        model=config.EMBED_MODEL, input=texts, encoding_format="float",
    )
    return np.array([d.embedding for d in resp.data], dtype=np.float32)


@_sync_retry
def chat(prompt, model=None, temperature=0, max_tokens=2500, messages=None):
    """同步一次性问答（合同分析等纯生成场景用，默认 GEN_MODEL=V4-Flash）。
    注意 V4 是推理模型，max_tokens 要给足，否则正文被思考过程吃光。"""
    resp = sync_client.chat.completions.create(
        model=model or config.GEN_MODEL,
        messages=messages or [{"role": "user", "content": prompt}],
        temperature=temperature, max_tokens=max_tokens,
    )
    return resp.choices[0].message.content


async def rerank_func(query, documents, top_n=None, **kwargs):
    """硅基流动 rerank API：对检索到的 chunk 精排。
    返回 LightRAG 要求的索引格式 [{"index": i, "relevance_score": s}, ...]。
    LightRAG 调用处包了 try/except，本函数抛错会自动降级用原始检索结果。"""
    if not documents:
        return []
    import httpx
    payload = {"model": config.RERANK_MODEL, "query": query, "documents": documents}
    if top_n:
        payload["top_n"] = top_n
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{config.BASE_URL}/rerank",
            headers={"Authorization": f"Bearer {config.SILICONFLOW_KEY}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {"index": r["index"], "relevance_score": r["relevance_score"]}
        for r in data["results"]
    ]


def make_embedding_func():
    """给 LightRAG 用的 EmbeddingFunc 包装"""
    from lightrag.utils import EmbeddingFunc
    return EmbeddingFunc(embedding_dim=config.EMBED_DIM, max_token_size=8192, func=embed_func)


async def make_rag():
    """创建并初始化一个 LightRAG 实例（加载已建好的图谱）。
    把初始化逻辑收口到这里，4 个文件不再各写一遍。"""
    from lightrag import LightRAG
    from lightrag.kg.shared_storage import initialize_pipeline_status
    rag = LightRAG(
        working_dir=config.WORKDIR,
        llm_model_func=llm_func,
        embedding_func=make_embedding_func(),
        rerank_model_func=rerank_func,   # 接入硅基流动重排，消除"未配置 rerank"告警
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    return rag

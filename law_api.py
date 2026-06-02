"""
FastAPI 实战 —— 把劳动法 AI 包成后端接口
核心学习点：真实公司里，AI 逻辑就是这样被包成 API，供前端 / App / 其他服务调用。

对比 law_app.py(Streamlit)：
  - Streamlit：又当前端又当后端，一个文件给【人】看
  - 这里(FastAPI)：纯后端，只返回 JSON 数据，给【程序】调用

一个隐藏亮点：
  law_app.py 里你踩过"事件循环冲突"的坑，写了一套持久化 loop 的 hack。
  FastAPI 原生就是 async 的，这里【完全不需要】那套 hack —— 这正是
  后端框架天生比 Streamlit 适合做 AI 服务的原因之一。

运行：  py -m uvicorn law_api:app --reload --port 8001
测试：  浏览器打开 http://127.0.0.1:8001/docs
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
import numpy as np
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import AsyncOpenAI
from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc
from lightrag.kg.shared_storage import initialize_pipeline_status

# ===== 配置：从 .env 读 Key，代码里不出现真 Key =====
load_dotenv()
KEY = os.getenv("SILICONFLOW_KEY")
BASE = "https://api.siliconflow.com/v1"
WORKDIR = "./lightrag_store"

# ===== 模型函数(和 law_app.py 一模一样)=====
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

# ===== 全局变量：知识图谱(启动时加载一次，所有请求共用)=====
rag = None

# ===== lifespan：服务【启动时】跑一次，加载知识图谱 =====
# 关键：模型/知识库只在启动时加载一次，不是每次请求都加载(那样会很慢)
@asynccontextmanager
async def lifespan(app: FastAPI):
    global rag
    print("⏳ 正在加载劳动法知识图谱...")
    rag = LightRAG(
        working_dir=WORKDIR, llm_model_func=llm_func,
        embedding_func=EmbeddingFunc(embedding_dim=1024, max_token_size=8192, func=embed_func),
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    print("✅ 知识图谱就绪，接口可以用了")
    yield   # ← yield 之前是"启动时"，之后是"关闭时"
    print("👋 服务关闭")

app = FastAPI(title="劳动法 AI 接口", lifespan=lifespan)

# ===== 请求体的"格式定义"(Pydantic)=====
# 这是 FastAPI 又一个香的地方：定义好格式，它自动校验+自动生成文档
class Question(BaseModel):
    question: str   # 调用方必须传一个字符串字段 question

# ===== 核心接口：POST /ask =====
# 和 fastapi_hello 的区别：那个是 GET(参数放URL)，这个是 POST(参数放请求体)
# 规律：查东西用 GET，提交数据用 POST。问问题算"提交"，所以用 POST。
@app.post("/ask")
async def ask(q: Question):
    answer = await rag.aquery(q.question, param=QueryParam(mode="hybrid"))
    return {
        "question": q.question,
        "answer": answer,
        "disclaimer": "本回答由AI根据公开法条生成，仅供参考，不构成正式法律意见。",
    }

# ===== 健康检查接口(生产项目标配，让运维知道服务还活着)=====
@app.get("/health")
def health():
    return {"status": "ok", "rag_loaded": rag is not None}

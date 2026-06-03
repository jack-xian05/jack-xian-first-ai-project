"""
FastAPI 实战 —— 把劳动法 AI 包成后端接口（给程序调用，返回 JSON）。

对比 law_app.py(Streamlit)：那个又当前端又当后端给【人】看；这里纯后端给【程序】调。
FastAPI 原生 async，不需要 Streamlit 那套持久化事件循环 hack。

生产化加固：
  - 鉴权：调 /ask 要带 X-API-Token 头（值在 .env 的 LAW_API_TOKEN），防止接口被盗刷烧额度
  - 限长：超长问题直接拒，防止超大输入烧 token
  - 引用核验：返回里标出回答引用的法条哪些可信、哪些可能编造
  - 错误处理：查询异常返回 503 而不是 500 堆栈

运行：  py -m uvicorn law_api:app --reload --port 8001
测试：  浏览器打开 http://127.0.0.1:8001/docs
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

import config
import citation_check
from llm_utils import make_rag
from lightrag import QueryParam

# ===== 全局：知识图谱（启动时加载一次，所有请求共用）=====
rag = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rag
    print("⏳ 正在加载劳动法知识图谱...")
    rag = await make_rag()
    print("✅ 知识图谱就绪，接口可以用了")
    yield
    print("👋 服务关闭")


app = FastAPI(title="劳动法 AI 接口", lifespan=lifespan)


# ===== 鉴权依赖 =====
def check_token(x_api_token: str = Header(default="")):
    """校验请求头里的 X-API-Token。未配置 LAW_API_TOKEN 时放行（方便本地调试）。"""
    if config.LAW_API_TOKEN and x_api_token != config.LAW_API_TOKEN:
        raise HTTPException(status_code=401, detail="无效的 API Token")


# ===== 请求体 =====
class Question(BaseModel):
    question: str = Field(..., min_length=1, max_length=config.MAX_QUESTION_LEN,
                          description=f"劳动法问题，最长 {config.MAX_QUESTION_LEN} 字")


# ===== 核心接口：POST /ask =====
@app.post("/ask")
async def ask(q: Question, x_api_token: str = Header(default="")):
    check_token(x_api_token)
    try:
        answer = await rag.aquery(q.question, param=QueryParam(mode="hybrid"))
    except Exception as e:
        # 上游 API 抖动/超时等，返回 503 让调用方知道是"暂时不可用"，而非代码 bug
        raise HTTPException(status_code=503, detail=f"AI 服务暂时不可用：{e}")

    verified, unverified = citation_check.verify(answer)
    return {
        "question": q.question,
        "answer": answer,
        "citations": {"verified": verified, "unverified": unverified},
        "disclaimer": "本回答由AI根据公开法条生成，仅供参考，不构成正式法律意见。",
    }


# ===== 健康检查（生产标配，让运维知道服务还活着）=====
@app.get("/health")
def health():
    return {"status": "ok", "rag_loaded": rag is not None}

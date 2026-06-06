"""
FastAPI 后端 —— 把劳动法 AI 包成接口，供前端(law_app.py)或其他程序调用。

特性：
  - 对话历史：接收 history，把多轮上下文拼进查询，支持"接着上一个问题问"
  - 鉴权：调 /ask 要带 X-API-Token 头(值在 .env 的 LAW_API_TOKEN)，防盗刷烧额度
  - 限流：/ask 每 IP 每分钟最多 10 次（slowapi），超限返回 429
  - 限长：question 超长直接拒(Pydantic 校验)
  - 引用核验：返回里标出回答引用的法条哪些可信、哪些可能编造
  - 错误处理：查询异常返回 503，空结果给友好兜底

运行：  py -m uvicorn law_api:app --reload --port 8000
测试：  浏览器打开 http://127.0.0.1:8000/docs
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import config
import citation_check
from llm_utils import make_rag
from lightrag import QueryParam

# ===== 限流器：按客户端 IP 计数，进程内存存储（单实例部署够用）=====
limiter = Limiter(key_func=get_remote_address)

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
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": f"请求过于频繁，请稍后再试（限制：{exc.detail}）"},
    )


# ===== 鉴权依赖 =====
def check_token(x_api_token: str = Header(default="")):
    """校验请求头里的 X-API-Token。未配置 LAW_API_TOKEN 时放行（方便本地调试）。"""
    if config.LAW_API_TOKEN and x_api_token != config.LAW_API_TOKEN:
        raise HTTPException(status_code=401, detail="无效的 API Token")


# ===== 请求体 =====
class Question(BaseModel):
    question: str = Field(..., min_length=1, max_length=config.MAX_QUESTION_LEN,
                          description=f"劳动法问题，最长 {config.MAX_QUESTION_LEN} 字")
    history: list = []   # 对话历史(可选)，[{role, content}, ...]，用于多轮上下文


# ===== 核心接口：POST /ask（每 IP 每分钟最多 RATE_LIMIT_ASK 次）=====
@app.post("/ask")
@limiter.limit(config.RATE_LIMIT_ASK)
async def ask(request: Request, q: Question, x_api_token: str = Header(default="")):
    check_token(x_api_token)

    # 有历史就把最近几轮拼进查询，支持多轮追问
    if q.history:
        ctx = "\n".join(
            f"{'用户' if m.get('role') == 'user' else '助手'}：{m.get('content', '')}"
            for m in q.history[-6:]
        )
        query = f"[对话历史]\n{ctx}\n\n[当前问题]\n{q.question}"
    else:
        query = q.question

    try:
        answer = await rag.aquery(query, param=QueryParam(mode="hybrid", user_prompt=config.CITATION_PROMPT))
    except Exception as e:
        # 上游 API 抖动/超时等，返回 503 告诉调用方"暂时不可用"，而非代码 bug
        raise HTTPException(status_code=503, detail=f"AI 服务暂时不可用：{e}")

    if not answer or not answer.strip():
        answer = "抱歉，暂时无法检索到相关法条，请换个问法重试。"

    verified, unverified = citation_check.verify(answer)
    return {
        "question": q.question,
        "answer": answer,
        "citations": {"verified": verified, "unverified": unverified},
        "disclaimer": "本回答由AI根据公开法条生成，仅供参考，不构成正式法律意见。",
    }


# ===== 健康检查 =====
@app.get("/health")
def health():
    return {"status": "ok", "rag_loaded": rag is not None}

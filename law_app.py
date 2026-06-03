"""
劳动法智能助手 —— 网页版（可部署）
技术栈：Streamlit + LightRAG(知识图谱RAG) + DeepSeek-V3
特点：图谱检索能跨多条法规综合回答 / 引用法条 / 防幻觉 / 聊天式交互

本地运行：  py -m streamlit run law_app.py
部署：      推到GitHub后用 Streamlit Community Cloud 一键部署
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
import asyncio
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from openai import AsyncOpenAI
from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc
from lightrag.kg.shared_storage import initialize_pipeline_status

# ===== 配置 =====
# 本地：从 .env 文件读；部署到 Streamlit Cloud：从网页后台的 secrets 读
load_dotenv()                                 # 本地：把 .env 里的值加载进来
try:
    KEY = st.secrets["SILICONFLOW_KEY"]       # 部署时优先从 Streamlit secrets 读
except Exception:
    KEY = os.getenv("SILICONFLOW_KEY")        # 本地从 .env 读，代码里不再出现真 Key
BASE = "https://api.siliconflow.com/v1"
WORKDIR = "./lightrag_store"

# ===== 页面设置 =====
st.set_page_config(page_title="劳动法智能助手", page_icon="⚖️", layout="centered")
st.title("⚖️ 劳动法智能助手")
st.caption("基于知识图谱(LightRAG) + DeepSeek，能跨多条法规综合解答你的劳动权益问题")

# ===== 模型函数 =====
async def llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
    return await openai_complete_if_cache(
        "deepseek-ai/DeepSeek-V3.1", prompt, system_prompt=system_prompt,  # 快且支持response_format(LightRAG需要)
        history_messages=history_messages, api_key=KEY, base_url=BASE, **kwargs,
    )

_embed_client = AsyncOpenAI(api_key=KEY, base_url=BASE)
async def embed_func(texts):
    resp = await _embed_client.embeddings.create(
        model="Qwen/Qwen3-Embedding-0.6B", input=texts, encoding_format="float",
    )
    return np.array([d.embedding for d in resp.data], dtype=np.float32)

# ===== 加载知识图谱（缓存，只加载一次）=====
# 关键：用一个【持久化的事件循环】，初始化和查询都跑在它上面。
# 否则 Streamlit 每次重跑新建循环，会和图谱内部的锁冲突（different event loop 错误）
@st.cache_resource
def load_loop_and_rag():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    async def _init():
        rag = LightRAG(
            working_dir=WORKDIR, llm_model_func=llm_func,
            embedding_func=EmbeddingFunc(embedding_dim=1024, max_token_size=8192, func=embed_func),
        )
        await rag.initialize_storages()
        await initialize_pipeline_status()
        return rag
    rag = loop.run_until_complete(_init())
    return loop, rag

if not os.path.exists(WORKDIR):
    st.error("⚠️ 知识图谱尚未构建，请先在本地运行 `py build_graph.py`")
    st.stop()

loop, rag = load_loop_and_rag()

# ===== 侧边栏：示例问题 =====
with st.sidebar:
    st.header("💡 试试这些问题")
    examples = [
        "试用期被辞退能拿到补偿吗？",
        "公司违法辞退我，能要多少赔偿？",
        "公司不交社保，我该怎么维权？",
        "怀孕期间被裁员合法吗？",
        "加班费怎么算？法定节假日呢？",
        "被裁员能拿到哪些钱？怎么算？",
    ]
    for ex in examples:
        if st.button(ex, key=ex, use_container_width=True):
            st.session_state.pending = ex

# ===== 聊天记录 =====
if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# ===== 处理提问 =====
def answer(question):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("正在查阅法规并综合分析..."):
            try:
                import requests
                history = st.session_state.messages[-6:]
                r = requests.post(
                    "http://localhost:8000/ask",
                    json={"question": question, "history": history},
                    timeout=120
                )
                resp = r.json()["answer"]
            except Exception as e:
                resp = "服务暂时不可用，请稍后重试。"
        import time
        def _stream():
            for char in resp:
                yield char
                time.sleep(0.01)
        st.write_stream(_stream())
        st.info("⚠️ 本回答由AI根据公开法条生成，仅供参考，不构成正式法律意见。具体问题请咨询执业律师或拨打12333。")
    st.session_state.messages.append({"role": "assistant", "content": resp})

# 来自侧边栏示例按钮
if "pending" in st.session_state:
    q = st.session_state.pop("pending")
    answer(q)

# 来自输入框
if prompt := st.chat_input("输入你的劳动法问题..."):
    answer(prompt)

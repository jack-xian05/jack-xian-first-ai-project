"""
劳动法智能助手 —— 网页版（基础版：仅智能问答）
技术栈：Streamlit + LightRAG(知识图谱RAG) + DeepSeek-V4-Flash
完整版(含合同分析/图片识别/历史)见 law_app_v2.py

本地运行：  py -m streamlit run law_app.py
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
import asyncio
import streamlit as st

import config
import citation_check
import auth
from llm_utils import make_rag

# ===== 页面设置 =====
st.set_page_config(page_title="劳动法智能助手", page_icon="⚖️", layout="centered")
auth.require_password()   # 公网访问口令门（设了 APP_PASSWORD 才生效）
st.title("⚖️ 劳动法智能助手")
st.caption("基于知识图谱(LightRAG) + DeepSeek，能跨多条法规综合解答你的劳动权益问题")


# ===== 加载知识图谱（缓存，只加载一次）=====
# 用一个【持久化事件循环】，初始化和查询都跑在它上面，
# 否则 Streamlit 每次重跑新建循环，会和图谱内部的锁冲突（different event loop 错误）
@st.cache_resource
def load_loop_and_rag():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    rag = loop.run_until_complete(make_rag())
    return loop, rag


if not os.path.exists(config.WORKDIR):
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
    question = question[:config.MAX_QUESTION_LEN]  # 限长，防超长输入烧 token
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("正在查阅法规并综合分析..."):
            from lightrag import QueryParam
            try:
                resp = loop.run_until_complete(rag.aquery(question, param=QueryParam(mode="hybrid")))
            except Exception as e:
                resp = f"抱歉，查询出错了：{e}\n\n请稍后重试。"
        st.markdown(resp)
        # 引用核验：标出回答里引用的法条哪些可信、哪些可能编造
        note = citation_check.format_note(resp)
        if note:
            st.caption(note)
        st.info("⚠️ 本回答由AI根据公开法条生成，仅供参考，不构成正式法律意见。具体问题请咨询执业律师或拨打12333。")
    st.session_state.messages.append({"role": "assistant", "content": resp})


if "pending" in st.session_state:
    answer(st.session_state.pop("pending"))

if prompt := st.chat_input("输入你的劳动法问题..."):
    answer(prompt)

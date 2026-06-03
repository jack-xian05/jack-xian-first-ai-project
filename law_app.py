"""
劳动法智能助手 —— 前端(前后端分离版)
本文件只做界面，AI 逻辑在后端 law_api.py。前端通过 HTTP 调后端，体现前后端分离架构。

运行需同时起两个服务：
  1. 后端： py -m uvicorn law_api:app --port 8000
  2. 前端： py -m streamlit run law_app.py

特点：多轮对话历史 / 流式输出 / 法条引用核验 / 访问口令
单进程、免后端的完整版见 law_app_v2.py。
"""
import time
import requests
import streamlit as st

import config
import auth
import citation_check

st.set_page_config(page_title="劳动法智能助手", page_icon="⚖️", layout="centered")
auth.require_password()   # 公网访问口令门（设了 APP_PASSWORD 才生效）

st.title("⚖️ 劳动法智能助手")
st.caption("基于知识图谱(LightRAG) + DeepSeek，能跨多条法规综合解答你的劳动权益问题")

# ===== 侧边栏：示例问题 =====
with st.sidebar:
    st.header("💡 试试这些问题")
    examples = [
        "试用期被辞退能拿到补偿吗？",
        "公司违法辞退我，能要多少赔偿？",
        "公司不交社保，我该怎么维权？",
        "怀孕期间被裁员合法吗？",
        "加班费怎么算？法定节假日呢？",
        "劳动仲裁的时效是多久？",
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


# ===== 处理提问（调后端 API）=====
def answer(question):
    question = question[:config.MAX_QUESTION_LEN]   # 限长
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("正在查阅法规并综合分析..."):
            try:
                headers = {}
                if config.LAW_API_TOKEN:
                    headers["X-API-Token"] = config.LAW_API_TOKEN
                history = st.session_state.messages[-6:]   # 带最近几轮做多轮上下文
                r = requests.post(
                    f"{config.BACKEND_URL}/ask",
                    json={"question": question, "history": history},
                    headers=headers, timeout=120,
                )
                resp = r.json()["answer"]
            except Exception:
                resp = "服务暂时不可用，请稍后重试。"

        # 流式输出（提升体感）
        def _stream():
            for char in resp:
                yield char
                time.sleep(0.01)
        st.write_stream(_stream())

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

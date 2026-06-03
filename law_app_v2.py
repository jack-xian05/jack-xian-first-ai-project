"""
劳动法智能助手 v2（完整版）
功能：智能问答(知识图谱) / PDF合同分析 / 图片识别 / 对话历史持久化
运行：py -m streamlit run law_app_v2.py
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
import asyncio
import sqlite3
import base64
from datetime import datetime

import streamlit as st
from lightrag import QueryParam

import config
import citation_check
import auth
from llm_utils import make_rag, sync_client, chat

st.set_page_config(page_title="劳动法智能助手", page_icon="⚖️", layout="wide")
auth.require_password()   # 公网访问口令门（设了 APP_PASSWORD 才生效）


# ===== 历史记录数据库 =====
def init_db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT DEFAULT '新对话',
        created_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conv_id INTEGER,
        role TEXT,
        content TEXT,
        created_at TEXT
    )""")
    conn.commit()
    conn.close()


def new_conversation():
    conn = sqlite3.connect(config.DB_PATH)
    cur = conn.execute(
        "INSERT INTO conversations (created_at) VALUES (?)",
        (datetime.now().strftime("%m-%d %H:%M"),)
    )
    conv_id = cur.lastrowid
    conn.commit()
    conn.close()
    return conv_id


def save_message(conv_id, role, content):
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(
        "INSERT INTO messages (conv_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (conv_id, role, content, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    if role == "user":
        title = content[:18] + "…" if len(content) > 18 else content
        conn.execute(
            "UPDATE conversations SET title=? WHERE id=? AND title='新对话'",
            (title, conv_id)
        )
    conn.commit()
    conn.close()


def load_conversations():
    conn = sqlite3.connect(config.DB_PATH)
    rows = conn.execute(
        "SELECT id, title, created_at FROM conversations ORDER BY id DESC LIMIT 30"
    ).fetchall()
    conn.close()
    return rows


def load_messages(conv_id):
    conn = sqlite3.connect(config.DB_PATH)
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conv_id=? ORDER BY id",
        (conv_id,)
    ).fetchall()
    conn.close()
    return [{"role": r, "content": c} for r, c in rows]


def delete_conversation(conv_id):
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
    conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    conn.commit()
    conn.close()


init_db()


# ===== 加载知识图谱（持久化事件循环，缓存）=====
@st.cache_resource
def load_loop_and_rag():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    rag = loop.run_until_complete(make_rag())
    return loop, rag


if not os.path.exists(config.WORKDIR):
    st.error("⚠️ 知识图谱尚未构建，请先运行 `py build_graph.py`")
    st.stop()

loop, rag = load_loop_and_rag()

# ===== 侧边栏：对话历史 =====
with st.sidebar:
    st.markdown("## ⚖️ 劳动法助手")

    if st.button("➕ 新对话", use_container_width=True, type="primary"):
        st.session_state.conv_id = new_conversation()
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.markdown("**历史对话**")

    conversations = load_conversations()
    for conv_id, title, created_at in conversations:
        is_current = st.session_state.get("conv_id") == conv_id
        col_btn, col_del = st.columns([5, 1])
        with col_btn:
            label = f"{'▶ ' if is_current else ''}{title}"
            if st.button(label, key=f"c{conv_id}", use_container_width=True):
                st.session_state.conv_id = conv_id
                st.session_state.messages = load_messages(conv_id)
                st.rerun()
        with col_del:
            if st.button("✕", key=f"d{conv_id}"):
                delete_conversation(conv_id)
                if st.session_state.get("conv_id") == conv_id:
                    st.session_state.conv_id = new_conversation()
                    st.session_state.messages = []
                st.rerun()

    st.divider()
    st.markdown("**💡 示例问题**")
    examples = [
        "试用期被辞退能拿补偿吗？",
        "公司违法辞退赔偿怎么算？",
        "怀孕期间被裁员合法吗？",
        "加班费怎么计算？",
        "公司不签合同怎么办？",
    ]
    for ex in examples:
        if st.button(ex, key=f"ex_{ex}", use_container_width=True):
            st.session_state.pending_question = ex

# ===== 初始化会话 =====
if "conv_id" not in st.session_state:
    st.session_state.conv_id = new_conversation()
if "messages" not in st.session_state:
    st.session_state.messages = []

# ===== 三个功能 Tab =====
tab1, tab2, tab3 = st.tabs(["💬 智能问答", "📄 合同分析", "🖼️ 图片识别"])

# ────────── Tab 1：智能问答 ──────────
with tab1:
    st.markdown("### 劳动权益智能咨询")

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    def answer(question):
        question = question[:config.MAX_QUESTION_LEN]  # 限长
        save_message(st.session_state.conv_id, "user", question)
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("正在查阅法规并综合分析..."):
                try:
                    resp = loop.run_until_complete(
                        rag.aquery(question, param=QueryParam(mode="hybrid"))
                    )
                except Exception as e:
                    resp = f"抱歉，查询出错了：{e}\n\n请稍后重试。"
            st.markdown(resp)
            note = citation_check.format_note(resp)   # 引用核验
            if note:
                st.caption(note)
            st.info("⚠️ 仅供参考，不构成法律意见。具体问题请咨询律师或拨打 12333。")
        save_message(st.session_state.conv_id, "assistant", resp)
        st.session_state.messages.append({"role": "assistant", "content": resp})

    if "pending_question" in st.session_state:
        answer(st.session_state.pop("pending_question"))

    if prompt := st.chat_input("输入你的劳动法问题..."):
        answer(prompt)

# ────────── Tab 2：合同分析 ──────────
with tab2:
    st.markdown("### 📄 劳动合同风险分析")
    st.caption("上传你的劳动合同 PDF，AI 找出违法条款和风险点")

    uploaded_pdf = st.file_uploader("上传劳动合同（PDF）", type=["pdf"])

    if uploaded_pdf:
        try:
            import pdfplumber
            with pdfplumber.open(uploaded_pdf) as pdf:
                contract_text = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )

            if not contract_text.strip():
                st.warning("无法提取文字，可能是扫描版 PDF，请切换到「图片识别」Tab 上传截图。")
            else:
                st.success(f"✅ 成功读取合同，共 {len(contract_text)} 字")
                with st.expander("查看提取的合同原文"):
                    st.text(contract_text[:3000] + ("…（已截断）" if len(contract_text) > 3000 else ""))

                analysis_type = st.radio(
                    "分析类型",
                    ["全面风险扫描", "违法条款检查", "缺失条款检查"],
                    horizontal=True
                )

                if st.button("开始分析", type="primary", key="analyze_pdf"):
                    text_chunk = contract_text[:config.MAX_CONTRACT_LEN]
                    prompts = {
                        "全面风险扫描": f"""你是一位专业劳动法律师，请全面分析以下劳动合同：

1. 【🔴 违法条款】明确违反《劳动合同法》的条款，标明条款位置和违反的法律条文
2. 【🟡 风险条款】对劳动者不利但未明确违法的条款，说明潜在风险
3. 【⚫ 缺失条款】法律要求必须具备但缺失的内容
4. 【⭐ 总体评价】用1-5星评价合同规范程度，并给出维权建议

【合同内容】
{text_chunk}""",
                        "违法条款检查": f"""请逐条检查以下劳动合同，找出所有违反《劳动法》《劳动合同法》的条款。
对每个违法条款：① 说明违法内容 ② 引用具体法律条文 ③ 建议如何修改或应对

【合同内容】
{text_chunk}""",
                        "缺失条款检查": f"""根据《劳动合同法》第17条，劳动合同必须包含9类必备条款。
请检查以下合同是否缺失，并说明每项缺失的法律后果和应对方法。

【合同内容】
{text_chunk}"""
                    }

                    with st.spinner("正在分析合同，请稍候..."):
                        try:
                            analysis = chat(prompts[analysis_type], temperature=0)
                        except Exception as e:
                            analysis = f"分析失败：{e}\n\n请稍后重试。"

                    st.markdown("### 📋 分析结果")
                    st.markdown(analysis)
                    note = citation_check.format_note(analysis)  # 核验合同分析里的法条引用
                    if note:
                        st.caption(note)
                    st.warning("⚠️ 以上分析由 AI 生成，仅供参考，不构成正式法律意见。")

        except ImportError:
            st.error("缺少依赖，请运行：`pip install pdfplumber`")
        except Exception as e:
            st.error(f"读取 PDF 失败：{e}")

# ────────── Tab 3：图片识别 ──────────
with tab3:
    st.markdown("### 🖼️ 图片内容识别分析")
    st.caption("上传工资条、合同截图、公司通知、仲裁文书等图片，AI 帮你解读")

    uploaded_img = st.file_uploader(
        "上传图片",
        type=["jpg", "jpeg", "png", "webp"],
        help="支持工资条、劳动合同截图、离职证明、仲裁通知等"
    )

    if uploaded_img:
        st.image(uploaded_img, caption="已上传图片", use_container_width=True)

        img_question = st.text_input(
            "你想了解什么？（可直接使用默认问题）",
            value="请识别图片中的文字内容，并从劳动法角度分析是否存在违规或风险点",
        )

        if st.button("分析图片", type="primary", key="analyze_img"):
            with st.spinner("正在识别分析图片..."):
                img_bytes = uploaded_img.getvalue()
                b64 = base64.b64encode(img_bytes).decode()
                img_type = uploaded_img.type or "image/jpeg"

                try:
                    resp = sync_client.chat.completions.create(
                        model=config.VL_MODEL,
                        messages=[{
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{img_type};base64,{b64}"
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": f"""你是一位专业劳动法咨询师。
{img_question}

请先提取图片中的关键文字信息，再从劳动法角度分析，如有违规请引用具体法律条文。"""
                                }
                            ]
                        }],
                        max_tokens=1500
                    )
                    result = resp.choices[0].message.content

                    st.markdown("### 📋 识别分析结果")
                    st.markdown(result)
                    st.warning("⚠️ 以上分析由 AI 生成，仅供参考，不构成正式法律意见。")

                except Exception as e:
                    st.error(f"图片分析失败：{e}")
                    st.info("提示：请确认 SiliconFlow 账号有 Qwen2.5-VL 模型的访问权限")

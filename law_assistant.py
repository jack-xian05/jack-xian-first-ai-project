"""
劳动法智能咨询助手（真实业务场景版）
比 demo 版多了3个"懂业务"的设计：
  1. 引用法条来源（法律场景必须可溯源，不能瞎编）
  2. 免责声明（AI法律建议的合规要求）
  3. 严格的"基于法条回答"提示词 + 低温度（减少幻觉）

运行：py -m streamlit run law_assistant.py
"""
import streamlit as st
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import Chroma

import os
from dotenv import load_dotenv
load_dotenv()
SILICONFLOW_KEY = os.getenv("SILICONFLOW_KEY")
BASE_URL = "https://api.siliconflow.cn/v1"

st.set_page_config(page_title="劳动法咨询助手", page_icon="⚖️")
st.title("⚖️ 劳动法智能咨询助手")
st.caption("帮你快速了解试用期、加班费、离职补偿等劳动权益")

# ===== 知识库初始化（缓存，只做一次）=====
@st.cache_resource
def init_retriever():
    docs = TextLoader("labor_law.txt", encoding="utf-8").load()
    # 法律条款按【】分段更合理，这里用稍大的块保证一条法规完整
    chunks = RecursiveCharacterTextSplitter(
        chunk_size=300, chunk_overlap=50, separators=["\n【", "\n\n", "\n", "。"]
    ).split_documents(docs)
    embeddings = OpenAIEmbeddings(model="Qwen/Qwen3-Embedding-0.6B", api_key=SILICONFLOW_KEY, base_url=BASE_URL)
    return Chroma.from_documents(chunks, embeddings).as_retriever(search_kwargs={"k": 3})

# temperature=0：法律场景要稳定、少发挥，减少幻觉
llm = ChatOpenAI(model="deepseek-ai/DeepSeek-V3", api_key=SILICONFLOW_KEY,
                 base_url=BASE_URL, temperature=0)

retriever = init_retriever()

# ===== 侧边栏：示例问题，方便演示 =====
with st.sidebar:
    st.header("💡 试试这些问题")
    st.markdown("""
    - 试用期最长能签多久？
    - 公司不签劳动合同怎么办？
    - 法定节假日加班怎么算工资？
    - 工作3年被辞退能拿多少补偿？
    - 试用期辞职要提前几天？
    """)

# ===== 主问答区 =====
question = st.text_input("请输入你的劳动法问题：", placeholder="例如：试用期最长能签多久？")

if st.button("咨询", type="primary") and question:
    with st.spinner("正在查阅法条..."):
        docs = retriever.invoke(question)
        context = "\n\n".join(d.page_content for d in docs)

        # 关键：严格的法律场景提示词
        prompt = f"""你是一位专业的劳动法咨询助手。请严格根据下面提供的【法律条款】回答用户问题。

要求：
1. 只能依据提供的法条回答，不得编造法律条文
2. 回答时必须指明依据的具体法律和条款（如《劳动合同法》第十九条）
3. 如果提供的法条无法回答该问题，明确说明"现有法条无法准确回答，建议咨询专业律师"
4. 用通俗易懂的语言解释，必要时举例

【法律条款】
{context}

【用户问题】{question}
"""
        answer = llm.invoke(prompt).content

    st.markdown("### 📋 咨询解答")
    st.markdown(answer)

    # 显示引用来源（法律场景核心：可溯源）
    with st.expander("📚 查看引用的法条原文"):
        for i, doc in enumerate(docs, 1):
            st.markdown(f"**来源 {i}：**")
            st.text(doc.page_content)

    # 免责声明（合规要求）
    st.warning("⚠️ 免责声明：本回答由AI根据公开法条生成，仅供参考，不构成正式法律意见。具体问题请咨询执业律师。")

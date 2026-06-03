"""
集中配置 —— 所有 Key、模型名、路径、限制都在这里，改一处全局生效。
之前模型名硬编码在 4 个文件里，改一次要改 4 处且容易漏，现在统一管理。
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ===== 凭证 =====
# 优先读 Streamlit secrets（云部署），本地回退到 .env，代码里不出现真 Key
def _get(name: str, default: str = "") -> str:
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)

SILICONFLOW_KEY = _get("SILICONFLOW_KEY")
BASE_URL = "https://api.siliconflow.com/v1"

# ===== 模型（按特长分工，详见 README「模型选型」）=====
# 建图谱：要稳定按格式抽实体，用 V3（已建好存盘，一般不重建）
BUILD_MODEL = "deepseek-ai/DeepSeek-V3"
# 知识图谱查询：LightRAG 关键词抽取需要【结构化 response_format】，实测只有 V3/V3.1 支持，
#              V4-Flash/V4-Pro 会报 "response_format type unavailable"，所以这里必须用 V3.1
LLM_MODEL = "deepseek-ai/DeepSeek-V3.1"
# 纯文本生成（合同分析等，不走 LightRAG、不需要 response_format）：用 V4-Flash，更快
GEN_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"
EMBED_DIM = 1024
VL_MODEL = "Qwen/Qwen2.5-VL-72B-Instruct"   # 多模态：图片识别

# ===== 路径 =====
WORKDIR = "./lightrag_store"        # 知识图谱数据
CORPUS_PATH = "labor_law.txt"       # 法规语料（引用核验也读它）
DB_PATH = "./chat_history.db"       # 对话历史

# ===== 接口安全（law_api.py 用）=====
# 调接口要带 X-API-Token 头，值=这里。没配则默认放行（方便本地调试）
LAW_API_TOKEN = _get("LAW_API_TOKEN")
MAX_QUESTION_LEN = 500              # 单次提问最大字数，防止超长输入烧 token
MAX_CONTRACT_LEN = 4000            # 合同分析截取的最大字数

# ===== 重试 =====
MAX_RETRIES = 3                     # API 调用失败重试次数
RETRY_BASE_DELAY = 1.0             # 指数退避基准秒数

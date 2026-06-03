# ⚖️ 劳动法智能助手

基于**知识图谱 RAG（LightRAG）** + 大语言模型的劳动法咨询助手。能跨多条法规综合分析，针对真实劳动权益场景（被辞退、加班费、社保、三期保护等）给出带法条依据的解答；并支持上传**劳动合同 PDF / 工资条截图**做风险分析。

> ⚠️ 本项目仅供学习与技术演示，AI 生成内容不构成正式法律意见。

---

## ✨ 功能特点

- **知识图谱检索**：用 LightRAG 把劳动法规构建成实体-关系图谱，能顺着关系链跨多条法规综合回答（普通向量 RAG 做不到）
- **真实场景覆盖**：覆盖试用期、经济补偿(N/N+1/2N)、违法解除、加班费、社保、工伤、医疗期、三期女职工保护、竞业限制、劳动仲裁等高频场景
- **📄 劳动合同分析**：上传劳动合同 PDF，自动提取文字并扫描违法条款 / 风险条款 / 缺失条款（pdfplumber 解析）
- **🖼️ 图片识别分析**：上传工资条、合同截图、仲裁文书等图片，用多模态模型（Qwen2.5-VL）识别内容并从劳动法角度解读
- **💬 多轮对话 + 历史持久化**：聊天式界面，对话记录用 SQLite 本地存储，可随时切换 / 删除历史会话
- **法条溯源 + 防幻觉**：回答标注具体法律依据，低温度 + 免责声明，减少编造

---

## 🏗️ 技术架构

```
用户提问 / 上传文件
   │
   ▼
Streamlit Web 界面（多 Tab：问答 / 合同分析 / 图片识别）
   │
   ├── 智能问答 → LightRAG (hybrid 模式)
   │      ├── 实体/关系抽取 → 知识图谱检索
   │      └── 向量检索 (Qwen3-Embedding, 1024维)
   │             │
   │             ▼
   │      DeepSeek-V4-Flash 综合生成带法条依据的回答
   │
   ├── 合同分析 → pdfplumber 提取文字 → DeepSeek-V3 风险扫描
   └── 图片识别 → Qwen2.5-VL-72B 多模态识别 + 劳动法解读
```

**技术栈**：Python · LightRAG · Streamlit · DeepSeek-V4-Flash / Qwen2.5-VL（硅基流动 API）· Qwen3-Embedding · SQLite · pdfplumber

> 说明：**建图谱用 DeepSeek-V3**（实体抽取要稳定输出，已构建一次存入 `lightrag_store/`，无需重建）；**查询生成用 DeepSeek-V4-Flash**（更快，且已验证兼容 LightRAG 所需的 response_format）。两个环节模型不同是有意为之。

---

## 🔧 工程实践 / 踩坑记录

> 这部分记录了开发中遇到的真实问题与解决思路。

1. **LightRAG 接国产 Embedding 的兼容问题**
   框架默认给 OpenAI 模型注入 `dimensions=1536` 参数做降维，但国产 Qwen Embedding（固定 1024 维）不支持，导致返回向量数量和维度错乱。通过逐层隔离测试（原生 API → openai SDK → 框架封装）定位根因，最终自实现 embedding 函数绕过，并关闭 base64 编码避免解码不兼容。

2. **Streamlit（同步）+ LightRAG（异步）的事件循环冲突**
   Streamlit 每次交互重跑脚本，`asyncio.run()` 反复新建事件循环，而 LightRAG 内部锁绑定到首次初始化的循环上，引发 "bound to a different event loop" 错误。解决方案：维护一个持久化事件循环，初始化与查询统一在该循环上执行。

3. **推理模型的 max_tokens 陷阱**
   换用 DeepSeek-V4-Flash 后发现回答时常空白或被截断。排查发现 V4 是**推理模型**，会先生成一大段思考（reasoning_content）再输出答案，原先较小的 `max_tokens` 被思考过程吃光。对比测试后确认：V4-Flash 比 V3.1 响应快约一倍，但需把 max_tokens 设足，否则正文没有预算。

---

## 🚀 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key：复制 .env.example 为 .env，填入硅基流动 Key
#    （部署到 Streamlit Cloud 时改用 secrets，代码已自动兼容两种方式）
cp .env.example .env

# 3. 构建知识图谱（首次运行，约几分钟；之后直接复用 lightrag_store/）
python build_graph.py

# 4. 启动 Web 应用（完整版，含合同分析 / 图片识别 / 对话历史）
streamlit run law_app_v2.py
```

浏览器访问 `http://localhost:8501`

> `law_app.py` 是只含「智能问答」的基础版，`law_app_v2.py` 是包含全部功能的完整版，推荐运行后者。

---

## 📂 项目结构

```
├── law_app_v2.py     # 主应用（完整版：问答 + 合同分析 + 图片识别 + 历史）
├── law_app.py        # 基础版（仅智能问答，用于对比演示）
├── law_api.py        # FastAPI 后端接口版（把 AI 能力包成 REST API）
├── build_graph.py    # 构建知识图谱脚本（一次性，用 V3 抽取实体）
├── labor_law.txt     # 劳动法规知识库（语料）
├── lightrag_store/   # 已构建的知识图谱数据（图谱 + 向量）
├── requirements.txt  # 依赖
├── .env.example      # 环境变量模板（复制为 .env 填入真实 Key）
└── README.md
```

---

## 📈 后续可优化方向

- 流式输出（提升响应体感）
- 简单问题走普通 RAG、复杂问题走图谱的智能分流
- 接入更完整的法规库与司法解释
- 扫描版 PDF 合同接入 OCR（目前扫描件需走「图片识别」Tab）

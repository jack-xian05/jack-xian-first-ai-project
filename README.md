# ⚖️ 劳动法智能助手

基于**知识图谱 RAG（LightRAG）** + 大语言模型的劳动法咨询助手。能跨多条法规综合分析，针对真实劳动权益场景（被辞退、加班费、社保、三期保护等）给出带法条依据的解答；并支持上传**劳动合同 PDF / 工资条截图**做风险分析。

🌐 **在线体验**：http://47.242.111.247:8501

> ⚠️ 本项目仅供学习与技术演示，AI 生成内容不构成正式法律意见。

---

## ✨ 功能特点

- **知识图谱检索**：用 LightRAG 把劳动法规构建成实体-关系图谱，能顺着关系链跨多条法规综合回答（普通向量 RAG 做不到）
- **真实场景覆盖**：试用期、经济补偿(N/N+1/2N)、违法解除、加班费、社保、工伤、医疗期、三期女职工保护、竞业限制、劳动仲裁等高频场景（含补充法规语料 `labor_law_extra.txt`）
- **📄 劳动合同分析**：上传劳动合同 PDF，自动提取文字并扫描违法条款 / 风险条款 / 缺失条款（pdfplumber 解析）
- **🖼️ 图片识别分析**：上传工资条、合同截图、仲裁文书等图片，用多模态模型（Qwen2.5-VL）识别内容并从劳动法角度解读
- **💬 多轮对话 + 流式输出 + 历史持久化**：聊天式界面，支持多轮上下文追问、逐字流式输出，对话记录用 SQLite 本地存储
- **🛡️ 法条引用核验（真·防幻觉）**：不止靠免责声明——从知识库建立"真实存在的法条"索引，对回答里引用的每条法条自动核验，**编造的法条号当场标红**
- **📊 自动化评估**：内置 20 题评估集 + 评测脚本，可复现地给出关键点召回率、法条召回率、引用幻觉数

---

## 🏗️ 技术架构

支持两种运行形态：

**A. 单体完整版**（`law_app_v2.py`，单进程，部署最简单）
```
用户提问 / 上传文件
   │
   ▼
Streamlit（多 Tab：问答 / 合同分析 / 图片识别）
   ├── 智能问答 → LightRAG(hybrid) → DeepSeek-V3.1 → 法条引用核验
   ├── 合同分析 → pdfplumber → DeepSeek-V4-Flash 风险扫描
   └── 图片识别 → Qwen2.5-VL-72B 多模态
```

**B. 前后端分离版**（`law_app.py` + `law_api.py`，体现工程分层）
```
Streamlit 前端(law_app.py)  ──HTTP──▶  FastAPI 后端(law_api.py)
  界面/流式/多轮历史                      鉴权 + 限长 + RAG + 引用核验
```

**技术栈**：Python · LightRAG · Streamlit · FastAPI · DeepSeek-V3.1 / V4-Flash / Qwen2.5-VL（硅基流动 API）· Qwen3-Embedding · SQLite · pdfplumber

### 模型选型（按特长分工，实测得出）

| 环节 | 模型 | 为什么选它 |
|------|------|-----------|
| 建知识图谱 | DeepSeek-V3 | 实体抽取要稳定按格式输出；已建好存盘无需重建 |
| **知识图谱查询** | **DeepSeek-V3.1** | LightRAG 关键词抽取需要**结构化 response_format**，实测只有 V3/V3.1 支持，V4 系列会报 `response_format type unavailable` |
| 合同分析（纯生成） | DeepSeek-V4-Flash | 不走 LightRAG、不需要 response_format，V4-Flash 响应更快 |
| 图片识别 | Qwen2.5-VL-72B | 多模态视觉模型 |

> 这个分工是真实踩坑后定的：一开始想全用更快的 V4-Flash，结果发现它不支持 LightRAG 的结构化输出（见下方踩坑记录 4），于是改为"图谱查询走 V3.1、纯生成走 V4-Flash"各取所长。

---

## 🔧 工程实践 / 踩坑记录

> 这部分记录了开发中遇到的真实问题与解决思路。

1. **LightRAG 接国产 Embedding 的兼容问题**
   框架默认给 OpenAI 模型注入 `dimensions=1536` 参数做降维，但国产 Qwen Embedding（固定 1024 维）不支持，导致返回向量数量和维度错乱。通过逐层隔离测试（原生 API → openai SDK → 框架封装）定位根因，最终自实现 embedding 函数绕过，并关闭 base64 编码避免解码不兼容。

2. **Streamlit（同步）+ LightRAG（异步）的事件循环冲突**
   Streamlit 每次交互重跑脚本，`asyncio.run()` 反复新建事件循环，而 LightRAG 内部锁绑定到首次初始化的循环上，引发 "bound to a different event loop" 错误。解决方案：维护一个持久化事件循环，初始化与查询统一在该循环上执行。

3. **推理模型的 max_tokens 陷阱**
   引入 DeepSeek-V4-Flash 做合同分析时，回答时常空白或被截断。排查发现 V4 是**推理模型**，会先生成一大段思考（reasoning_content）再输出答案，原先较小的 `max_tokens` 被思考过程吃光。结论：用推理模型必须把 max_tokens 设足，否则正文没有预算。

4. **V4 不支持 LightRAG 的结构化 response_format**
   想把查询模型从 V3.1 升到更快的 V4-Flash，单测一个问题"通过"了，但跑评估集时大面积报错 `response_format type unavailable`。复盘发现：单测之所以"通过"是因为 LightRAG **缓存**了之前 V3.1 的关键词抽取结果，没真的调 V4。LightRAG 的关键词抽取依赖结构化 JSON 输出，实测只有 V3/V3.1 支持。**教训：验证要避开缓存、用未跑过的样本**——最终定为图谱查询用 V3.1、纯生成用 V4-Flash。

5. **从"能跑"到"工程化"的重构**
   初版把 `llm_func`/`embed_func` 在多个文件里复制粘贴、模型名硬编码、API 调用裸奔。重构为：`config.py` 集中配置、`llm_utils.py` 公共模块（含指数退避重试）、`law_api.py` 加接口鉴权与输入限长、新增法条引用核验与自动化评估。

---

## 🚀 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 Key：复制 .env.example 为 .env，填入硅基流动 Key（部署到云用 secrets，代码已兼容）
cp .env.example .env

# 3. 构建知识图谱（首次；之后复用 lightrag_store/）
python build_graph.py
python add_docs.py        # 可选：把补充法规 labor_law_extra.txt 增量并入图谱
```

**方式 A —— 单体完整版（推荐，一条命令）：**
```bash
streamlit run law_app_v2.py
```

**方式 B —— 前后端分离版（需起两个服务）：**
```bash
py -m uvicorn law_api:app --port 8000      # 终端1：后端
streamlit run law_app.py                   # 终端2：前端
```

浏览器访问 `http://localhost:8501`

---

## ☁️ 部署上线

已部署在阿里云 ECS（http://47.242.111.247:8501）。生产架构 `公网 → nginx(80/443, HTTPS) → streamlit(127.0.0.1:8501)`，systemd 保活、崩溃自重启。前端用访问口令（`APP_PASSWORD`）防止公网刷爆 API 额度。

完整步骤见 [deploy/DEPLOY.md](deploy/DEPLOY.md)，配置文件在 `deploy/`（systemd 单元 + nginx 反代）。

---

## 📂 项目结构

```
├── law_app_v2.py     # 单体完整版（问答 + 合同分析 + 图片识别 + 历史）★推荐
├── law_app.py        # 前后端分离版的前端（调后端 API + 流式 + 多轮）
├── law_api.py        # FastAPI 后端（鉴权 + 限长 + 多轮历史 + 引用核验）
├── build_graph.py    # 构建知识图谱（一次性，用 V3 抽取实体）
├── add_docs.py       # 增量并入补充法规到图谱
├── config.py         # 集中配置（Key / 模型 / 路径 / 限制，改一处全局生效）
├── llm_utils.py      # 公共 LLM/Embedding 模块（含指数退避重试）
├── citation_check.py # 法条引用核验（防幻觉）
├── auth.py           # Streamlit 访问口令门（公网防刷额度）
├── eval/
│   ├── eval_set.json # 20 题评估集（含应引用法条 + 关键点）
│   └── run_eval.py   # 评测脚本（算召回率 / 幻觉率）
├── deploy/           # 阿里云 ECS 部署：systemd + nginx + HTTPS
│   ├── DEPLOY.md     # 手把手部署指南
│   ├── law-app.service       # systemd 常驻配置
│   └── nginx-law-app.conf    # nginx 反代 + WebSocket 配置
├── labor_law.txt         # 劳动法规知识库（主语料）
├── labor_law_extra.txt   # 补充法规（仲裁/加班/三期/社保等）
├── lightrag_store/   # 已构建的知识图谱数据（图谱 + 向量）
├── requirements.txt
├── .env.example
└── README.md
```

---

## 📊 质量评估

法律问答正确性是生命线，因此内置可复现的自动化评估：

```bash
py eval/run_eval.py        # 跑全部 20 题
py eval/run_eval.py 5      # 只跑前 5 题（快速验证）
```

评估三个指标：**关键点召回率**（标准答案要点覆盖度）、**法条召回率**（应引用法条的命中率）、**引用幻觉数**（编造的法条数，理想为 0）。

**当前实测结果**（20 题，知识图谱查询走 DeepSeek-V3.1）：

| 指标 | 数值 |
|------|------|
| 关键点平均召回率 | **87.9%** |
| 法条平均召回率 | **65.0%** |
| 引用幻觉总数 | **0** ✅ |

> 解读：**0 幻觉**说明"RAG 接地 + 引用核验"的防幻觉设计有效，没有编造法条。**法条召回率 65%** 是当前主要短板——回答常给对要点但未必显式引用具体条号，这也是下一步要优化的方向（在提示词里强制要求标注条号）。
>
> 注：评估过程顶部出现过几次 `Connection Error`，被指数退避重试自动救回，20 题全部完成——侧面验证了重试机制有效。

---

## 📈 后续可优化方向

- **提升法条引用召回率**（当前 65%）：在提示词中强制要求标注具体条号
- 简单问题走普通 RAG、复杂问题走图谱的智能分流
- 接入更完整的法规库与司法解释
- 扫描版 PDF 合同接入 OCR（目前扫描件需走「图片识别」Tab）
- 评估接入 LLM-as-judge，覆盖"解释是否准确"（现有指标只验证关键点/条号是否出现）

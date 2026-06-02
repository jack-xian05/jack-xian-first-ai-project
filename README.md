# ⚖️ 劳动法智能助手

基于**知识图谱 RAG（LightRAG）** + 大语言模型的劳动法咨询助手。能跨多条法规综合分析，针对真实劳动权益场景（被辞退、加班费、社保、三期保护等）给出带法条依据的解答。

> ⚠️ 本项目仅供学习与技术演示，AI 生成内容不构成正式法律意见。

---

## ✨ 功能特点

- **知识图谱检索**：用 LightRAG 把劳动法规构建成实体-关系图谱，能顺着关系链跨多条法规综合回答（普通向量 RAG 做不到）
- **真实场景覆盖**：覆盖试用期、经济补偿(N/N+1/2N)、违法解除、加班费、社保、工伤、医疗期、三期女职工保护、竞业限制、劳动仲裁等 24 类高频场景
- **法条溯源**：回答标注具体法律依据，可追溯
- **防幻觉设计**：基于知识库回答 + 免责声明，避免编造
- **聊天式 Web 界面**：Streamlit 构建，支持多轮对话和示例问题

---

## 🏗️ 技术架构

```
用户提问
   │
   ▼
Streamlit Web 界面
   │
   ▼
LightRAG (hybrid 模式)
   ├── 实体/关系抽取 → 知识图谱检索
   └── 向量检索 (Qwen3-Embedding)
   │
   ▼
DeepSeek-V4-Flash 综合生成带法条依据的回答
```

**技术栈**：Python · LightRAG · Streamlit · DeepSeek（硅基流动 API）· Qwen Embedding

---

## 🔧 工程实践 / 踩坑记录

> 这部分记录了开发中遇到的真实问题与解决思路。

1. **LightRAG 接国产 Embedding 的兼容问题**
   框架默认给 OpenAI 模型注入 `dimensions=1536` 参数做降维，但国产 Qwen Embedding（固定 1024 维）不支持，导致返回向量数量和维度错乱。通过逐层隔离测试（原生 API → openai SDK → 框架封装）定位根因，最终自实现 embedding 函数绕过，并关闭 base64 编码避免解码不兼容。

2. **Streamlit（同步）+ LightRAG（异步）的事件循环冲突**
   Streamlit 每次交互重跑脚本，`asyncio.run()` 反复新建事件循环，而 LightRAG 内部锁绑定到首次初始化的循环上，引发 "bound to a different event loop" 错误。解决方案：维护一个持久化事件循环，初始化与查询统一在该循环上执行。

3. **GraphRAG 延迟优化**
   hybrid 模式单次问答涉及多次 LLM 调用，延迟较高。通过模型降级（DeepSeek-V3 → V4-Flash，实测快约一倍）优化响应速度。

---

## 🚀 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key（在 law_app.py 中填入，或用 Streamlit secrets）

# 3. 构建知识图谱（首次运行，约几分钟）
python build_graph.py

# 4. 启动 Web 应用
streamlit run law_app.py
```

浏览器访问 `http://localhost:8501`

---

## 📂 项目结构

```
├── law_app.py        # Streamlit Web 应用主程序
├── build_graph.py    # 构建知识图谱脚本
├── labor_law.txt     # 劳动法规知识库
├── lightrag_store/   # 已构建的知识图谱数据
├── requirements.txt  # 依赖
└── README.md
```

---

## 📈 后续可优化方向

- 流式输出（提升响应体感）
- 简单问题走普通 RAG、复杂问题走图谱的智能分流
- 接入更完整的法规库与司法解释
- 增加用户对话历史持久化

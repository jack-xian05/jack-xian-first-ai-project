"""
往已有知识图谱里【增量插入】补充法规(labor_law_extra.txt)。
和 build_graph.py 一样用 BUILD_MODEL(V3) 抽实体，复用 llm_utils 公共模块，不再重复造轮子。

运行：py add_docs.py
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
import asyncio
from lightrag import LightRAG
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.kg.shared_storage import initialize_pipeline_status

import config
from llm_utils import make_embedding_func

EXTRA_CORPUS = "labor_law_extra.txt"


# 增量建图同样用 BUILD_MODEL(V3)，与 build_graph.py 保持一致
async def build_llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
    return await openai_complete_if_cache(
        config.BUILD_MODEL, prompt,
        system_prompt=system_prompt, history_messages=history_messages,
        api_key=config.SILICONFLOW_KEY, base_url=config.BASE_URL, **kwargs,
    )


async def main():
    rag = LightRAG(
        working_dir=config.WORKDIR,
        llm_model_func=build_llm_func,
        embedding_func=make_embedding_func(),
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    with open(EXTRA_CORPUS, "r", encoding="utf-8") as f:
        content = f.read()
    print(f"开始插入补充法规（{EXTRA_CORPUS}）...")
    await rag.ainsert(content)
    print("✅ 补充法规插入完成！")


asyncio.run(main())

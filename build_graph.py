"""
建图谱脚本：用 labor_law.txt 构建 LightRAG 知识图谱，存到 lightrag_store。
建好后，网页应用只需加载、查询，不用重建（部署时把 lightrag_store 一起带上即可）。

注意：建图谱用 config.BUILD_MODEL(V3)，查询用 config.LLM_MODEL(V4-Flash)，见 config.py 说明。
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
import asyncio
from lightrag import LightRAG
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.kg.shared_storage import initialize_pipeline_status

import config
from llm_utils import embed_func, make_embedding_func


# 建图用 BUILD_MODEL(V3)，所以单独定义，不用 llm_utils.llm_func(那是查询用的 V4)
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
    print("开始构建知识图谱（数据较多，请耐心等几分钟）...")
    with open(config.CORPUS_PATH, "r", encoding="utf-8") as f:
        await rag.ainsert(f.read())
    print("✅ 知识图谱构建完成！已存入", config.WORKDIR)


asyncio.run(main())

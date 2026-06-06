"""
清理知识图谱里 status=failed 的残留文档（如某次插入中途超时失败留下的半成品）。
只删失败状态的文档，不碰正常文档。删除不抽实体，但若实体被多文档共享，
LightRAG 可能对其重新汇总（少量 LLM 调用），属正常。

用法：python cleanup_failed.py
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
import asyncio
import json
from pathlib import Path

import config
from llm_utils import make_embedding_func, llm_func


async def main():
    from lightrag import LightRAG
    from lightrag.kg.shared_storage import initialize_pipeline_status

    ds_path = Path(config.WORKDIR) / "kv_store_doc_status.json"
    ds = json.loads(ds_path.read_text(encoding="utf-8")) if ds_path.exists() else {}
    # 清理"未完成"的残留：failed(失败) + processing(卡一半)，都该删掉重建
    failed = [k for k, v in ds.items() if v.get("status") in ("failed", "processing")]
    if not failed:
        print("没有 failed/processing 残留文档，无需清理。")
        return
    print(f"发现 {len(failed)} 个未完成文档：{[k[:24] + '..' for k in failed]}")

    rag = LightRAG(working_dir=config.WORKDIR, llm_model_func=llm_func,
                   embedding_func=make_embedding_func(),
                   llm_model_max_async=2, default_llm_timeout=300)
    await rag.initialize_storages()
    await initialize_pipeline_status()

    for doc_id in failed:
        await rag.adelete_by_doc_id(doc_id)
        print(f"🗑 已删除失败文档：{doc_id[:24]}..")
    print("✅ 清理完成。")


if __name__ == "__main__":
    asyncio.run(main())

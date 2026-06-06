"""
对账式同步（reconcile）——让知识图谱始终与种子清单 seed_laws.json 一致。

和 add_docs.py 的区别：add_docs 只会【插入】，本脚本是真正的"同步"：
  • 新增：seed 里新增的法规 → 插入图谱
  • 变更：法规内容变了（修订）→ 删旧版 + 插新版（按稳定 doc_id 原地替换）
  • 删除：法规从 seed 移除（废止）→ 从图谱删除   ← 这是 add_docs 做不到、却最关键的
  • 去重：每部法钉死稳定 doc_id `law-{md5(法名)}`，同一部永远一个文档，不会堆叠

为什么删除最关键：法律场景里，给用户答一条【已废止】的法条，比"查不到"更危险。
所以"实时/真实"的难点不在爬取，在于失效数据的【对账删除】。

依赖 LightRAG ≥1.4 的 adelete_by_doc_id + ainsert(ids=...) 指定稳定ID（已确认本机1.4.16支持）。
只管理自己创建的 `law-*` 文档，不碰手写语料(labor_law.txt 等)建的文档。

用法：
  python crawl_npc.py            # ① 先抓取/更新本地缓存 npc_laws/
  python sync_graph.py --dry-run # ② 先看对账计划（不动图谱、不烧API）
  python sync_graph.py           # ③ 真正执行同步（增/改/删，会调用LLM建图）
"""
import os
os.environ["EMBEDDING_USE_BASE64"] = "false"
import sys
import asyncio
import hashlib
import json
from datetime import date
from pathlib import Path

import config
from crawl_npc import safe_name, CACHE_DIR, SEED_FILE

MANIFEST = Path("graph_manifest.json")   # 台账：记录图谱里【我们管理的】法规 doc_id + 内容哈希
DRY = "--dry-run" in sys.argv


def doc_id_of(name: str) -> str:
    """每部法的稳定 doc_id：只跟法名有关，内容变了ID不变 → 便于原地替换/删除。"""
    return "law-" + hashlib.md5(name.encode("utf-8")).hexdigest()


def hash_of(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def load_desired() -> dict:
    """期望态 = seed 里有 url 且本地有缓存的法规 → {法名: (含溯源头的全文, url)}。"""
    seed = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    desired = {}
    for item in seed["laws"]:
        name, url = item["name"], item.get("url", "").strip()
        cf = CACHE_DIR / f"{safe_name(name)}.txt"
        if url and cf.exists():
            desired[name] = (cf.read_text(encoding="utf-8"), url)
    return desired


def load_graph_doc_ids() -> set:
    """读图谱里真实存在的文档 doc_id。用于自愈台账漂移：
    若 cleanup 等把图谱里的 doc 删了、台账却没更新，靠它发现并重建。"""
    p = Path(config.WORKDIR) / "kv_store_doc_status.json"
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding="utf-8")).keys())


def plan(desired: dict, manifest: dict, graph_ids: set):
    """算出对账计划：哪些新增/更新/删除/未变。纯逻辑，不碰图谱。
    自愈：台账说同步过、但图谱里实际没有这个 doc_id（漂移）→ 当新增重建。"""
    add, update, skip = [], [], []
    for name, (content, _url) in desired.items():
        h = hash_of(content)
        in_graph = doc_id_of(name) in graph_ids
        if name not in manifest or not in_graph:        # 没台账 / 台账与图谱漂移 → 重建
            add.append(name)
        elif manifest[name]["hash"] != h:
            update.append(name)
        else:
            skip.append(name)
    delete = [n for n in manifest if n not in desired]   # 台账有、seed没了 = 废止/移除
    return add, update, skip, delete


async def main():
    desired = load_desired()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    add, update, skip, delete = plan(desired, manifest, load_graph_doc_ids())

    print(f"对账计划：新增 {len(add)}｜更新 {len(update)}｜删除 {len(delete)}｜未变 {len(skip)}")
    for n in add:    print(f"  ➕ 新增：{n}")
    for n in update: print(f"  ♻ 更新：{n}")
    for n in delete: print(f"  🗑 删除(废止/移除)：{n}")
    if DRY:
        print("\n[dry-run] 仅预览，未改动图谱。去掉 --dry-run 执行。")
        return
    if not (add or update or delete):
        print("图谱已与种子清单一致，无需同步。")
        return

    # 真正执行：建 LightRAG（用 BUILD_MODEL 抽实体，与 add_docs/build_graph 一致）
    from lightrag import LightRAG
    from lightrag.llm.openai import openai_complete_if_cache
    from lightrag.kg.shared_storage import initialize_pipeline_status
    from llm_utils import make_embedding_func

    async def build_llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
        # 带重试：建图抽实体时硅基流动可能限流/超时，退避重试避免整篇文档失败
        last = None
        for attempt in range(config.MAX_RETRIES):
            try:
                return await openai_complete_if_cache(
                    config.BUILD_MODEL, prompt, system_prompt=system_prompt,
                    history_messages=history_messages, api_key=config.SILICONFLOW_KEY,
                    base_url=config.BASE_URL, **kwargs,
                )
            except Exception as e:
                last = e
                print(f"  ⚠ 建图LLM调用失败({type(e).__name__})，{config.RETRY_BASE_DELAY*(2**attempt):.0f}s后重试...")
                await asyncio.sleep(config.RETRY_BASE_DELAY * (2 ** attempt))
        raise last

    # 降并发(默认4→2)避免被限流拖慢导致超时；抬高单次超时给慢调用留余量
    rag = LightRAG(working_dir=config.WORKDIR, llm_model_func=build_llm_func,
                   embedding_func=make_embedding_func(),
                   llm_model_max_async=2, default_llm_timeout=300)
    await rag.initialize_storages()
    await initialize_pipeline_status()

    for name in add:
        content, url = desired[name]
        did = doc_id_of(name)
        await rag.ainsert(content, ids=[did], file_paths=[url])
        manifest[name] = {"doc_id": did, "hash": hash_of(content), "source_url": url,
                          "synced_at": date.today().isoformat()}
        print(f"➕ 已新增：{name}")

    for name in update:
        content, url = desired[name]
        did = doc_id_of(name)
        await rag.adelete_by_doc_id(manifest[name]["doc_id"])   # 删旧版
        await rag.ainsert(content, ids=[did], file_paths=[url])  # 插新版（同ID）
        manifest[name] = {"doc_id": did, "hash": hash_of(content), "source_url": url,
                          "synced_at": date.today().isoformat()}
        print(f"♻ 已更新：{name}")

    for name in delete:
        await rag.adelete_by_doc_id(manifest[name]["doc_id"])
        del manifest[name]
        print(f"🗑 已删除(废止/移除)：{name}")

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 对账完成：新增{len(add)} 更新{len(update)} 删除{len(delete)}；图谱现含 {len(manifest)} 部受管法规")


if __name__ == "__main__":
    asyncio.run(main())

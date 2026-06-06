"""
诊断：法条召回暴跌，是"检索没捞到条号"还是"检索到了但生成没引"。
对每道题用 only_need_context 取【检索上下文】(不生成，省钱)，检查期望引用的条号在不在。
  - 条号在上下文 → 检索OK，问题在生成阶段(没引/格式不符) → 调 prompt / rerank
  - 条号不在上下文 → 检索没捞到(稀释/top-K不足) → 调检索(top-K / rerank)
运行：python eval/diag_retrieval.py [题数]
"""
import os, sys, re, json, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from llm_utils import make_rag
from lightrag import QueryParam

EVAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_set.json")


def article_of(cite: str):
    """《劳动合同法》第六十三条 -> ('劳动合同法', '第六十三条')"""
    m = re.search(r'《([^》]+)》(第[一二三四五六七八九十百零两]+条)', cite)
    return (m.group(1), m.group(2)) if m else (None, cite)


async def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    cases = json.load(open(EVAL_FILE, encoding="utf-8"))["cases"]
    if limit:
        cases = cases[:limit]
    rag = await make_rag()

    total = art_in = full_in = 0
    miss = []
    for c in cases:
        cites = c.get("citations", [])
        if not cites:
            continue
        ctx = await rag.aquery(c["question"], param=QueryParam(mode="hybrid", only_need_context=True)) or ""
        for cite in cites:
            total += 1
            _, art = article_of(cite)
            has_art, has_full = art in ctx, cite in ctx
            art_in += has_art
            full_in += has_full
            if not has_art:
                miss.append((c["id"], cite))
            print(f"[{c['id']:>2}] 期望 {cite:<24} 条号{'✅检索到' if has_art else '❌没检索到'}  全称在上下文:{'✅' if has_full else '❌'}")

    print("\n" + "=" * 58)
    print(f"期望引用总数：{total}")
    print(f"  条号出现在检索上下文：{art_in} ({art_in/total*100:.0f}%)   ← 检索捞到了的")
    print(f"  全称《法》第X条在上下文：{full_in} ({full_in/total*100:.0f}%)")
    print(f"  条号压根没检索到：{len(miss)} ({len(miss)/total*100:.0f}%)   ← 检索侧丢的")
    print("=" * 58)
    print("判读：")
    print("  '没检索到'占多 → 检索稀释/top-K不足 → 调检索(rerank、调大top-K)")
    print("  '检索到了'占多但召回低 → 生成没引/格式不符 → 调prompt/rerank把条号顶到最前")


if __name__ == "__main__":
    asyncio.run(main())

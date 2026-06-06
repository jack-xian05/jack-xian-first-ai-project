"""
评估脚本 —— 自动跑评估集，给劳动法助手的回答打分。
为什么重要：法律问答正确性是生命线。没有 eval 就是"凭感觉说效果好"，
有了 eval 就能给出可复现的数字：关键点召回率、法条引用准确率、幻觉率。

三个指标：
  1. 关键点召回率：标准答案的要点，回答覆盖了多少
  2. 法条引用召回率：应该引用的法条，回答引用了多少
  3. 引用幻觉数：回答里引用了知识库中【不存在】的法条（越低越好，理想为 0）

运行：
  py eval/run_eval.py            # 跑全部 20 题（约几分钟，会调 API）
  py eval/run_eval.py 5          # 只跑前 5 题（快速验证脚本）
"""
import os, sys, json, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import citation_check
from llm_utils import make_rag
from lightrag import QueryParam

EVAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_set.json")


def _cite_key(cite: str):
    """'《劳动合同法》第十九条' -> ('劳动合同法','十九')，解析失败返回 None。
    归一化掉'中华人民共和国'前缀，这样模型写全称、评估集写简称也能对上。"""
    m = citation_check._CITATION.search(cite)
    return (citation_check._normalize_law(m.group(1)), m.group(2)) if m else None


def _norm(s: str) -> str:
    """关键点匹配归一化：'两'与'二'在中文数字里通用（两年=二年、两倍=二倍），统一成'二'再比，
    避免'答案写两年、评估集写二年'被误判成漏掉要点。"""
    return s.replace("两", "二")


def score_case(answer: str, case: dict):
    """给单题打分，返回各项指标"""
    ans_n = _norm(answer)
    kws = case["keywords"]
    kw_hit = [k for k in kws if _norm(k) in ans_n]
    kw_miss = [k for k in kws if _norm(k) not in ans_n]
    kw_recall = len(kw_hit) / len(kws) if kws else 1.0

    # 法条召回：按 (法名归一化, 条号) 集合比对，而非裸子串。
    # 否则模型写《中华人民共和国劳动合同法》第十九条、评估集写《劳动合同法》第十九条，
    # 子串不连续会被误判成漏引（曾导致法条召回假性归零）。
    cites = case["citations"]
    ans_keys = {(citation_check._normalize_law(law), art)
                for law, art in citation_check._CITATION.findall(answer)}
    hit = lambda c: _cite_key(c) in ans_keys
    if case.get("cite_any") and cites:
        # 等价法条：列出的多条里任一命中即算（如《劳动法》第五十条 与《劳动合同法》第三十条
        # 都讲"及时足额支付工资"，模型引其一即正确）。
        ok = any(hit(c) for c in cites)
        cite_recall = 1.0 if ok else 0.0
        cite_miss = [] if ok else cites
    else:
        cite_hit = [c for c in cites if hit(c)]
        cite_miss = [c for c in cites if not hit(c)]
        cite_recall = len(cite_hit) / len(cites) if cites else 1.0

    _, unverified = citation_check.verify(answer)  # 编造的法条
    return {
        "kw_recall": kw_recall, "kw_hit": kw_hit, "kw_miss": kw_miss,
        "cite_recall": cite_recall, "cite_miss": cite_miss,
        "hallucinated": unverified,
    }


async def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    with open(EVAL_FILE, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    if limit:
        cases = cases[:limit]

    print(f"加载知识图谱，准备评估 {len(cases)} 题...\n")
    rag = await make_rag()

    kw_recalls, cite_recalls, total_halluc = [], [], 0
    for c in cases:
        try:
            # 注入与 law_api 线上一致的引用指令，保证"评估即线上"
            ans = await rag.aquery(c["question"],
                                   param=QueryParam(mode="hybrid", user_prompt=config.CITATION_PROMPT))
        except Exception as e:
            ans = None
            print(f"⚠️ [{c['id']}] 查询异常：{e}")
        ans = ans or ""   # 查询失败时按空答案算分（全漏）
        s = score_case(ans, c)
        kw_recalls.append(s["kw_recall"])
        cite_recalls.append(s["cite_recall"])
        total_halluc += len(s["hallucinated"])

        flag = "✅" if s["kw_recall"] >= 0.6 and s["cite_recall"] >= 0.5 and not s["hallucinated"] else "⚠️"
        print(f"{flag} [{c['id']:>2}] {c['question']}")
        print(f"     关键点 {s['kw_recall']*100:.0f}% | 法条 {s['cite_recall']*100:.0f}%", end="")
        if s["cite_miss"]:
            print(f" | 漏引: {'、'.join(s['cite_miss'])}", end="")
        if s["hallucinated"]:
            print(f" | 🔴编造: {'、'.join(s['hallucinated'])}", end="")
        print()

    n = len(cases)
    print("\n" + "=" * 50)
    print("📊 评估汇总")
    print(f"   样本数：          {n}")
    print(f"   关键点平均召回率： {sum(kw_recalls)/n*100:.1f}%")
    print(f"   法条平均召回率：   {sum(cite_recalls)/n*100:.1f}%")
    print(f"   引用幻觉总数：     {total_halluc}  (理想=0)")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())

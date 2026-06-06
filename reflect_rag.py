"""
反思式 RAG —— 给单轮 RAG 加一个"会自我纠错的循环"。

比原来的单轮 RAG（lightrag_query.py / chat_rag.py）多了什么：
  原来：提问 → 检索回答 → 核验只是【标红给用户看】 → 完（错了也就错了）
  现在：提问 → 检索回答 → 核验 → 【不合格就带着问题反馈回去重答】→ 合格才输出

核心就是一个【带判断的循环】。判断逻辑直接复用你的 citation_check：
  - 回答里有"编造的法条"(unverified) → 不合格，重来
  - 回答里一条真实法条都没引用        → 不合格，重来（正是要打的 65% 召回率痛点）
  - 干净且至少引了 1 条真法条          → 合格，输出
  - 转够 MAX_ATTEMPTS 次还不行         → 兜底停（防死循环，等于 supervisor 的"超次数就 end"）

—— 概念对照 LangGraph（你在 supervisor.py 学的那套）——
  本文件的 state 字典         ≈ LangGraph 的 State
  answer_node()              ≈ 一个 graph 节点(node)
  judge() 返回 "retry"/"stop" ≈ add_conditional_edges 的条件函数(_should_continue)
  while + judge 的回边        ≈ 条件边里 {"retry": "answer", "stop": END}
等你想换成真 LangGraph，把这三块对号入座即可，逻辑一模一样。
"""
from __future__ import annotations
import asyncio

from lightrag import QueryParam

import config
import citation_check
from llm_utils import make_rag


# ────────── 一个"节点"：检索 + 回答 ──────────
async def answer_node(rag, question: str, feedback: str = "") -> str:
    """走一遍 LightRAG 拿答案。feedback 非空时（即重试轮），把上一轮的问题反馈
    拼进提问里，引导模型这次答得更规范——这就是'循环带着上一轮结果再来'的关键。"""
    query = question
    if feedback:
        query = (
            f"{question}\n\n"
            f"【上一轮回答存在问题，请改正后重答】{feedback} "
            f"务必只引用【真实存在】的法条，并标注到具体条号（如《劳动合同法》第三十九条）。"
        )
    return await rag.aquery(query, param=QueryParam(mode="hybrid"))


# ────────── "条件边"：判断要不要再来一轮 ──────────
def judge(answer: str, attempt: int, max_attempts: int) -> tuple[str, str]:
    """返回 (决定, 反馈)。决定 = "stop" 或 "retry"。
    这就是整个项目最该抄走的 20%：达标没 / 超次数没 / 还有问题没。"""
    verified, unverified = citation_check.verify(answer)

    # 兜底：转够次数，无论好坏都停（防死循环）—— 对应 supervisor 的 iteration >= max_iter
    if attempt >= max_attempts:
        return "stop", ""

    # 不合格①：引用了知识库里不存在的法条（模型编的）
    if unverified:
        return "retry", f"你引用了知识库中不存在的法条：{('、'.join(unverified))}，可能是编造的。"

    # 不合格②：一条具体法条都没引用（要点对、但没落到条号——正是 65% 召回率的病根）
    if not verified:
        return "retry", "你没有引用任何具体法条条号，请补上支撑结论的真实法条。"

    # 合格：没编 + 至少引了 1 条真法条
    return "stop", ""


# ────────── 把节点和条件边串成循环（≈ build_graph + invoke）──────────
async def reflect_answer(question: str, max_attempts: int = 3, verbose: bool = True) -> dict:
    """反思循环主入口。返回最终 state，含答案、轮次、最后一次核验结果。"""
    rag = await make_rag()

    feedback = ""
    answer = ""
    for attempt in range(1, max_attempts + 1):
        answer = await answer_node(rag, question, feedback)
        decision, feedback = judge(answer, attempt, max_attempts)

        if verbose:
            v, u = citation_check.verify(answer)
            print(f"  ↻ 第 {attempt} 轮：真法条 {len(v)} 条，可疑 {len(u)} 条 → {decision}")

        if decision == "stop":
            break

    return {
        "question": question,
        "answer": answer,
        "attempts": attempt,
        "note": citation_check.format_note(answer),  # 给用户看的核验说明（复用你已有的）
    }


# ────────── 直接运行：命令行试一试 ──────────
async def _main():
    print("✅ 反思式 RAG 就绪（输入 quit 退出）\n")
    while True:
        q = input("你：").strip()
        if q.lower() in ("quit", "exit", "退出"):
            print("再见！")
            break
        if not q:
            continue
        result = await reflect_answer(q, max_attempts=config.MAX_RETRIES)
        print(f"\nAI（共 {result['attempts']} 轮）：\n{result['answer']}")
        if result["note"]:
            print(f"\n{result['note']}")
        print("-" * 50)


if __name__ == "__main__":
    asyncio.run(_main())

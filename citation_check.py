"""
法条引用核验 —— 真·防幻觉的关键一环。
思路：模型回答里会引用"《劳动合同法》第三十九条"这种法条。我们从知识库语料里
建一份"真实存在的法条"索引，把回答里的引用逐条比对：
  - 命中索引 → 可信
  - 不在索引 → 标红警告（可能是模型编的，法律场景这是硬伤）

注意：这只能核验"该法条是否存在于知识库"，不保证模型对法条的【解释】100%正确，
但已经能挡掉最危险的"凭空编造法条号"这类幻觉。
"""
import re
import config

# 匹配 "《某某法》第X条"，X 为中文数字
_CITATION = re.compile(r'《([^》]+?)》第([一二三四五六七八九十百零两]+)条')


def _normalize_law(name: str) -> str:
    """法律名归一化：去掉'中华人民共和国'前缀，便于匹配"""
    return name.replace("中华人民共和国", "").strip()


def build_index(corpus_path: str = None) -> set:
    """从语料里抽出所有真实存在的 (法律名, 条号)，建成索引集合"""
    path = corpus_path or config.CORPUS_PATH
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    index = set()
    for law, article in _CITATION.findall(text):
        index.add((_normalize_law(law), article))
    return index


# 模块加载时建一次索引，复用
_INDEX = None
def _get_index():
    global _INDEX
    if _INDEX is None:
        _INDEX = build_index()
    return _INDEX


def verify(answer: str):
    """核验回答里的所有法条引用。
    返回 (verified, unverified)：两个列表，元素是 '《法》第X条' 字符串。"""
    index = _get_index()
    verified, unverified, seen = [], [], set()
    for law, article in _CITATION.findall(answer):
        key = (_normalize_law(law), article)
        cite = f"《{law}》第{article}条"
        if cite in seen:
            continue
        seen.add(cite)
        (verified if key in index else unverified).append(cite)
    return verified, unverified


def format_note(answer: str) -> str:
    """生成一段给用户看的核验说明（Markdown）"""
    verified, unverified = verify(answer)
    if not verified and not unverified:
        return ""
    lines = []
    if verified:
        lines.append("✅ 已核实引用（存在于知识库）：" + "、".join(verified))
    if unverified:
        lines.append("⚠️ **未能核实的引用**（知识库中未找到，请谨慎对待，可能是模型生成有误）："
                     + "、".join(unverified))
    return "\n\n".join(lines)


if __name__ == "__main__":
    # 自测：一真一假
    idx = build_index()
    print(f"知识库共收录 {len(idx)} 条法条引用")
    demo = "根据《劳动合同法》第八十七条，违法解除按2N赔偿；又据《劳动合同法》第九十九条无此规定。"
    v, u = verify(demo)
    print("可信：", v)
    print("可疑：", u)
    print("---说明---")
    print(format_note(demo))

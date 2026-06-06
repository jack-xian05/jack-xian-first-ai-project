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

# 匹配 "《某某法》第X条"，X 为中文数字（用于从模型回答里抽取引用）
_CITATION = re.compile(r'《([^》]+?)》第([一二三四五六七八九十百零两]+)条')

# 建索引专用：额外识别"《法》第X条、第Y条、第Z条"这种同一部法连写多条的枚举。
# 只认紧跟在《法》第X条之后、用顿号或"和"连接的条号，保持严格、不会把无关条号误纳入。
_CITATION_ENUM = re.compile(
    r'《([^》]+?)》第([一二三四五六七八九十百零两]+)条((?:[、和]第[一二三四五六七八九十百零两]+条)*)'
)
_ARTICLE = re.compile(r'第([一二三四五六七八九十百零两]+)条')

# 抓取语料里每部法规前的【法规名称】头（crawl_npc.py 生成）。
# 有了它，就能把该法正文里裸写的"第X条"全部登记成 (该法, X)，而不必依赖《法》第X条这种交叉引用。
_LAW_HEADER = re.compile(r'^【法规名称】\s*(.+?)\s*$')


def _normalize_law(name: str) -> str:
    """法律名归一化：去掉'中华人民共和国'前缀，便于匹配"""
    return name.replace("中华人民共和国", "").strip()


def build_index(corpus_paths=None) -> set:
    """从所有语料里抽出真实存在的 (法律名, 条号)，建成索引集合。
    默认读 config.CORPUS_FILES（主语料 + 补充语料），缺失的文件自动跳过。"""
    import os
    paths = corpus_paths or getattr(config, "CORPUS_FILES", [config.CORPUS_PATH])
    if isinstance(paths, str):
        paths = [paths]
    index = set()
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        # 第①趟（交叉引用）：取 "《法》第X条"，并把其后连写的 "、第Y条" 也归到同一部法。
        # 适用于手写语料里"根据《X法》第Y条"这类跨法引用。
        for law, first, trailing in _CITATION_ENUM.findall(text):
            norm = _normalize_law(law)
            index.add((norm, first))
            for art in _ARTICLE.findall(trailing):
                index.add((norm, art))
        # 第②趟（按【法规名称】分节）：抓取语料里每部法的正文是裸写"第X条"的，
        # 读到 header 后把本节内所有"第X条"都登记给当前这部法——这样全文每一条都可核验。
        # （正文里裸写的"第X条"基本都指本法；引用别法时会带《》，已由第①趟正确归属。）
        current = None
        for line in text.splitlines():
            m = _LAW_HEADER.match(line.strip())
            if m:
                current = _normalize_law(m.group(1))
                continue
            if current:
                for art in _ARTICLE.findall(line):
                    index.add((current, art))
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

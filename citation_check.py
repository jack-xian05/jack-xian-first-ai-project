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

# ===== 精确查表（条号→原文）专用 =====
# 行首条号：把整条原文从全文里切出来。必须锚定行首(^)，否则正文里"依据第X条"这种
# 交叉引用会被误当成新条开头、把原文切碎。
_ARTICLE_HEAD = re.compile(r'^第([一二三四五六七八九十百零两]+)条')
# 章/节标题与目录：作条文分隔符（遇到就结束上一条，自身不是条文内容）
_CHAPTER_HEAD = re.compile(r'^(?:第[一二三四五六七八九十百零两]+[章节]|目\s*录)')
NPC_DIR = "npc_laws"   # crawl_npc.py 落地的官方法规全文目录（逐条原文，带【来源】溯源）


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


# ===== 精确查表：条号 → 条文原文 =====
# 与上面的"存在性索引"分工：存在性索引防幻觉(判条号真假)，精确表回填权威原文(保内容准确)。
# 为什么要它：语义检索定位到法条后，让模型转述条文仍可能说错；直接查表返回立法原文，零转述误差。
# 数据源是 npc_laws/ 官方全文，逐条切分。
def build_article_index(npc_dir: str = None) -> dict:
    """把官方全文逐条切成完整原文，建 {(法名归一化, 条号中文数字): 原文} 字典。"""
    import os, glob
    npc_dir = npc_dir or NPC_DIR
    index = {}
    if not os.path.isdir(npc_dir):
        return index
    for path in sorted(glob.glob(os.path.join(npc_dir, "*.txt"))):
        law, cur, buf = None, None, []

        def flush():
            nonlocal cur, buf
            if law and cur and buf:
                index.setdefault((law, cur), "".join(buf).strip())  # 同条号保留首现(正文优先于零散引用)
            cur, buf = None, []

        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                s = raw.strip()
                h = _LAW_HEADER.match(s)
                if h:
                    flush(); law = _normalize_law(h.group(1)); continue
                if _CHAPTER_HEAD.match(s):
                    flush(); continue                       # 章/节/目录:中断当前条
                a = _ARTICLE_HEAD.match(s)
                if a:
                    flush(); cur, buf = a.group(1), [s]      # 新条开始
                elif cur:
                    buf.append("\n" + s)                     # 续行并入当前条
            flush()
    return index


_ARTICLE_INDEX = None
def _get_article_index():
    global _ARTICLE_INDEX
    if _ARTICLE_INDEX is None:
        _ARTICLE_INDEX = build_article_index()
    return _ARTICLE_INDEX


def lookup_article(cite: str):
    """输入 '《劳动合同法》第十九条'(或含'中华人民共和国'全称)，返回该条立法原文；查不到返回 None。"""
    m = _CITATION.search(cite)
    if m:
        law, art = m.group(1), m.group(2)
    else:  # 容错:宽松解析"法名 + 中文数字"
        lm = re.search(r'([一-龥]+?(?:法|条例|规定|解释))', cite)
        am = re.search(r'([一二三四五六七八九十百零两]+)', cite)
        if not (lm and am):
            return None
        law, art = lm.group(1), am.group(1)
    return _get_article_index().get((_normalize_law(law), art))


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

    print("\n=== 精确查表（条号→原文）===")
    aidx = build_article_index()
    print(f"精确表收录 {len(aidx)} 条立法原文")
    for q in ["《劳动合同法》第十九条", "《中华人民共和国劳动合同法》第三十九条", "《工伤保险条例》第十五条"]:
        txt = lookup_article(q)
        print(f"\n[{q}]\n{txt[:120] + '…' if txt else '（未收录）'}")

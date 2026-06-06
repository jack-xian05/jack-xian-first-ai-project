"""
定向抓取官方劳动法规（人大网 / 政府网纯HTML页）→ 喂给你的知识库。

设计原则（前面几轮讨论的结论，落到代码里）：
  1. 不做"自由爬虫"：只抓 seed_laws.json 里你钉死URL的法规，可控、不污染生命线。
  2. 只取官方源：URL 全是 npc.gov.cn / gov.cn 官方页，权威性在系统之外背书。
  3. 全程溯源：每条法规带 source_url + 来源 + 抓取时间，台账另记内容哈希。
  4. 随时更新（你要的核心）：每次重抓算哈希，内容【变了才重抓】，没变直接用缓存。
  5. 不重复：每部法规一个缓存文件，总语料每次【全量重建】（覆盖，不追加）→ 永不堆积重复。
  6. 礼貌抓取：串行 + 限速。
  7. 对接已有管线：生成 labor_law_extra3.txt → 跑 add_docs.py 增量进图谱。

用法：
  python crawl_npc.py          # 抓所有有url的法规（变了才重抓），重建总语料
  python add_docs.py labor_law_extra3.txt   # 把法规并入知识图谱
"""
from __future__ import annotations
import hashlib
import html
import json
import re
import time
from datetime import date
from pathlib import Path

import requests

# ────────── 配置 ──────────
SEED_FILE = Path("seed_laws.json")
CACHE_DIR = Path("npc_laws")                # 每部法规一个缓存文件（含溯源头）
OUT_FILE = Path("labor_law_extra3.txt")     # 总语料，每次全量重建，喂 add_docs.py
SOURCE_LOG = Path("source_log.json")         # 溯源台账：来源/链接/时间/哈希
REQUEST_DELAY = 2.0                          # 每次请求间隔(秒)，礼貌限速
HEADERS = {"User-Agent": "Mozilla/5.0 (labor-law-study; personal learning)"}

# 页面导航/页脚噪声：这些不是法条正文，清掉，别污染图谱
# 前缀型（行以这些词开头就整行丢，因后面常跟时间/栏目名）
_NOISE_PREFIX = re.compile(
    r"^(当前位置|浏览字号|打印|分享|字号|来源[:：]|责任编辑|网站地图|关于我们|版权所有|主办|备案|扫一扫|"
    r"个人中心|无障碍|网站无障碍|您当前|您的位置|首页|搜索|客户端|微信|微博|设为首页|加入收藏|繁体|简体|"
    r"中文版|English|关注|登录邮箱|邮箱系统|RSS|导航|返回顶部|字体[:：]|阅读量|发布时间|发布日期)"
)
# 整行型（纯数字、日期、模板残留、注释、独立URL、字号按钮【大】、纯括号/标点碎片）
_NOISE_FULL = re.compile(
    r"^(\d+|\d{4}-\d{2}-\d{2}.*|/?enpproperty.*|<!--.*|-->|https?://\S+|【[大中小]】|[\[\]()、，。\s|·-]+)$"
)


# ────────── 抓取 + 清洗 ──────────
def fetch_html(url: str, retries: int = 3) -> str:
    """GET 官方页面，自动处理编码（老页面可能是GBK）。带简单重试，扛偶发SSL/超时。"""
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or r.encoding   # 防中文乱码
            return r.text
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))   # 退避后重试
    raise last


# 正文起点锚：法规真正开始的标志（目录 / 第一条 / 颁布说明行 / 《X》已...通过公布）
# 用"最强标记"定位正文起点，丢掉它上面所有页头——包括标题和标题后夹的订阅/字号等CMS碎片
_ANCHOR = re.compile(
    r"^(目\s*录|第一条|（.*(通过|公布|施行|修正|实施|令第|号).*）|《.*》.*(通过|公布|施行))"
)
# 页脚起点：正文之后出现这些就截断（相关链接/版权/备案等）
_FOOTER = re.compile(r"(相关链接|相关稿件|相关报道|扫一扫|主办单位|主办[:：]|版权所有|网站标识码|ICP备|公安.*备|分享到)")


def extract_text(raw: str, name: str = "") -> str:
    """HTML → 干净法条文本。脏数据进图谱=脏图谱，这步是质量闸门。
    策略：去标签 → 行级去噪 → 锚点裁剪（丢正文前的导航、正文后的页脚）。"""
    text = re.sub(r"(?is)<(script|style|head).*?</\1>", "", raw)   # 删脚本/样式/头
    text = re.sub(r"(?s)<[^>]+>", "\n", text)                      # 标签→换行
    text = html.unescape(text)                                    # 解码 &#160; &amp; 等实体
    text = text.replace("　", " ").replace("\xa0", " ")    # 全角/不间断空格
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or _NOISE_PREFIX.match(s) or _NOISE_FULL.match(s):
            continue
        if len(s) <= 2 and not re.search(r"第.+条|章", s):       # 丢极短导航碎片
            continue
        lines.append(s)

    # 锚点裁剪：优先定位"最强内容标记"（目录/第一条/颁布行），丢掉其上方全部页头+CMS碎片
    start = None
    for i, s in enumerate(lines):
        if _ANCHOR.match(s):
            start = i
            break
    if start is None:                      # 没找到强锚，退而用标题行
        for i, s in enumerate(lines):
            if s == name:
                start = i
                break
    lines = lines[start or 0:]
    # 页脚裁剪：正文之后第一次出现页脚标志就截断
    for i, s in enumerate(lines):
        if i > 5 and _FOOTER.search(s):
            lines = lines[:i]
            break

    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return cleaned.strip()


def content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|（）()\s]', "_", name)


# ────────── 主流程 ──────────
def main() -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    seed = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    log = json.loads(SOURCE_LOG.read_text(encoding="utf-8")) if SOURCE_LOG.exists() else {}

    fetched, skipped, missing = 0, 0, 0
    for item in seed["laws"]:
        name, url = item["name"], item.get("url", "").strip()
        cache_file = CACHE_DIR / f"{safe_name(name)}.txt"
        if not url:
            print(f"⚪ 待补URL，跳过：{name}")
            missing += 1
            continue

        # 随时更新的核心：内容没变 + 缓存还在 → 不重抓
        try:
            text = extract_text(fetch_html(url), name)
        except Exception as e:
            print(f"⚠ 抓取失败：{name} -> {e}")
            continue
        h = content_hash(text)
        if log.get(name, {}).get("hash") == h and cache_file.exists():
            print(f"⏭  内容未变：{name}（{len(text)} 字）")
            skipped += 1
            time.sleep(REQUEST_DELAY)
            continue

        # 写该法规的缓存文件（带溯源头），覆盖旧的 → 天然去重
        header = (
            f"【法规名称】{name}\n【效力级别】{item.get('level', '')}\n"
            f"【来源】{url}\n【抓取日期】{date.today().isoformat()}\n{'-' * 40}\n"
        )
        cache_file.write_text(header + text + "\n", encoding="utf-8")
        log[name] = {"source_url": url, "fetched_at": date.today().isoformat(), "hash": h}
        fetched += 1
        print(f"✅ 已更新：{name}（{len(text)} 字）")
        time.sleep(REQUEST_DELAY)

    # 全量重建总语料：把所有缓存文件拼起来覆盖写 → 永不重复堆积
    parts = []
    for item in seed["laws"]:
        cf = CACHE_DIR / f"{safe_name(item['name'])}.txt"
        if cf.exists():
            parts.append(cf.read_text(encoding="utf-8"))
    if parts:
        OUT_FILE.write_text("\n".join(parts), encoding="utf-8")
        SOURCE_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n📊 完成：重抓 {fetched}，未变 {skipped}，待补URL {missing}；总语料含 {len(parts)} 部法规")
    if parts:
        print(f"📦 {OUT_FILE}（全量重建）+ {SOURCE_LOG}（溯源台账）")
        print(f"➡  下一步：python add_docs.py labor_law_extra3.txt")


if __name__ == "__main__":
    main()

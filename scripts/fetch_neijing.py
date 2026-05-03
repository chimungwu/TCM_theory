"""
fetch_neijing.py
從公領域來源抓取《黃帝內經》33 篇高頻引用篇之原文，
並更新到 docs/原文/ 底下對應檔案。

修正版重點：
  1. Wikisource 不再使用「黃帝內經素問/篇名」錯誤路徑。
  2. 改用 Wikisource 實際頁面：「黃帝內經/素問第X卷」、「黃帝內經/靈樞第X卷」。
  3. 若該卷含多篇，會依篇名與篇次擷取指定篇章，不會整卷寫入。
  4. ctext 改為備援來源，並嘗試 /zh 路徑；若 403，會跳過。
  5. 加入 retry、去重、段落品質檢查與較保守的標題雜訊過濾。

使用方式：
  python scripts/fetch_neijing.py
  python scripts/fetch_neijing.py --chapter 至真要大論
  python scripts/fetch_neijing.py --chapter 至真要大論 --dry-run
  python scripts/fetch_neijing.py --book 素問
  python scripts/fetch_neijing.py --source wikisource
  python scripts/fetch_neijing.py --source ctext

需要套件：
  pip install requests beautifulsoup4
"""

import argparse
import copy
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

try:
    import requests
    from bs4 import BeautifulSoup
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("缺少套件。請先執行：pip install requests beautifulsoup4")
    sys.exit(1)


# 33 篇高頻引用篇 = (篇名, 王冰本篇次, ctext.org 之 slug)
CHAPTERS = {
    "素問": [
        ("上古天真論",   1, "shang-gu-tian-zhen-lun"),
        ("生氣通天論",   3, "sheng-qi-tong-tian-lun"),
        ("陰陽應象大論", 5, "yin-yang-ying-xiang-da-lun"),
        ("靈蘭秘典論",   8, "ling-lan-mi-dian-lun"),
        ("六節藏象論",   9, "liu-jie-zang-xiang-lun"),
        ("五臟生成",     10, "wu-zang-sheng-cheng"),
        ("五臟別論",     11, "wu-zang-bie-lun"),
        ("脈要精微論",   17, "mai-yao-jing-wei-lun"),
        ("經脈別論",     21, "jing-mai-bie-lun"),
        ("宣明五氣",     23, "xuan-ming-wu-qi"),
        ("太陰陽明論",   29, "tai-yin-yang-ming-lun"),
        ("熱論",         31, "re-lun"),
        ("瘧論",         35, "nve-lun"),
        ("咳論",         38, "ke-lun"),
        ("舉痛論",       39, "ju-tong-lun"),
        ("風論",         42, "feng-lun"),
        ("痺論",         43, "bi-lun"),
        ("痿論",         44, "wei-lun"),
        ("厥論",         45, "jue-lun"),
        ("奇病論",       47, "qi-bing-lun"),
        ("骨空論",       60, "gu-kong-lun"),
        ("水熱穴論",     61, "shui-re-xue-lun"),
        ("調經論",       62, "tiao-jing-lun"),
        ("六元正紀大論", 71, "liu-yuan-zheng-ji-da-lun"),
        ("至真要大論",   74, "zhi-zhen-yao-da-lun"),
    ],
    "靈樞": [
        ("本神",       8, "ben-shen"),
        ("經脈",       10, "jing-mai"),
        ("營衛生會",   18, "ying-wei-sheng-hui"),
        ("癲狂",       22, "dian-kuang"),
        ("決氣",       30, "jue-qi"),
        ("海論",       33, "hai-lun"),
        ("五味",       56, "wu-wei"),
        ("百病始生",   66, "bai-bing-shi-sheng"),
    ],
}

# Wikisource 目錄使用的異體、簡稱、錯字或通行差異。
TITLE_ALIASES = {
    "五臟生成": ["五藏生成"],
    "五臟別論": ["五藏別論"],
    "陰陽應象大論": ["陰陽應像大論"],
    "宣明五氣": ["宣明五氣篇"],
    "咳論": ["欬論"],
    "水熱穴論": ["水熱宂論"],
    "癲狂": ["癲狂病"],
}

CTEXT_BASE = "https://ctext.org/huangdi-neijing"
WIKISOURCE_BASE = "https://zh.wikisource.org/zh-hant"
DOCS_BASE = Path(__file__).resolve().parent.parent / "docs" / "原文"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}
TIMEOUT = 25


def create_session():
    """建立具備 retry 的 requests session。"""
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


SESSION = create_session()


# ─── 數字與卷次 ─────────────────────────────────────────────────────

def _num_to_chinese(n):
    """阿拉伯數字轉中文數字（限 1-99）。"""
    chars = "零一二三四五六七八九"
    if n < 10:
        return chars[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + chars[n - 10]
    tens, ones = divmod(n, 10)
    return chars[tens] + "十" + (chars[ones] if ones else "")


def _volume_no(book, pian_num):
    """依 Wikisource《黃帝內經》目錄取得篇次所在卷數。"""
    if book == "素問":
        ranges = [
            (1, 4, 1), (5, 7, 2), (8, 11, 3), (12, 16, 4),
            (17, 18, 5), (19, 20, 6), (21, 24, 7), (25, 30, 8),
            (31, 34, 9), (35, 38, 10), (39, 41, 11), (42, 45, 12),
            (46, 49, 13), (50, 55, 14), (56, 59, 15), (60, 61, 16),
            (62, 62, 17), (63, 65, 18), (66, 68, 19), (69, 70, 20),
            (71, 73, 21), (74, 74, 22), (75, 78, 23), (79, 81, 24),
        ]
    elif book == "靈樞":
        ranges = [
            (1, 4, 1), (5, 9, 2), (10, 12, 3), (13, 19, 4),
            (20, 28, 5), (29, 40, 6), (41, 47, 7), (48, 56, 8),
            (57, 64, 9), (65, 72, 10), (73, 77, 11), (78, 81, 12),
        ]
    else:
        return None

    for start, end, vol in ranges:
        if start <= pian_num <= end:
            return vol
    return None


def _wikisource_page_path(book, pian_num):
    """產生 Wikisource 實際頁面路徑。"""
    vol = _volume_no(book, pian_num)
    if vol is None:
        return None
    return f"黃帝內經/{book}第{_num_to_chinese(vol)}卷"


# ─── 清洗與截章 ─────────────────────────────────────────────────────

def _clean_for_match(text):
    """去除空白與標點，用於篇名比對。"""
    return re.sub(r"[\s\.:：。，,、；;！!？?\-—《》「」『』（）()【】\[\]\"'〈〉]+", "", text or "")


def _title_candidates(title):
    return [title] + TITLE_ALIASES.get(title, [])


def _heading_matches(text, title, pian_num):
    """判斷 h2/h3 標題是否為目標篇章。"""
    cleaned = _clean_for_match(text)
    candidates = [_clean_for_match(t) for t in _title_candidates(title)]
    if any(c and c in cleaned for c in candidates):
        return True

    # 保險：若標題內含篇次數字，也視為可能命中。
    pian_cn = _num_to_chinese(pian_num)
    return f"第{pian_cn}" in cleaned or str(pian_num) in cleaned


def _extract_chapter_content(content, soup, book, title, pian_num):
    """從一個 Wikisource 卷頁中，只擷取目標篇章。"""
    headings = content.find_all(["h2", "h3", "h4"], recursive=True)
    target_heading = None
    for h in headings:
        if _heading_matches(h.get_text("", strip=True), title, pian_num):
            target_heading = h
            break

    # 該卷只有一篇，或找不到標題時，退回整個 content。
    # 對至真要大論這類單篇卷可正常運作；多篇卷若找不到標題，後續 validation 會擋下過短/異常內容。
    if target_heading is None:
        return content

    frag = soup.new_tag("div")
    for node in target_heading.next_siblings:
        if getattr(node, "name", None) in {"h2", "h3", "h4"}:
            break
        frag.append(copy.copy(node))
    return frag


def _is_title_artifact(text, book, title):
    """判斷某段文字是否只是頁面標題／導覽／節錨點，應排除。"""
    text = text.strip()
    if not text:
        return True
    if len(text) > 80:
        return False

    candidates = []
    for t in _title_candidates(title):
        candidates += [
            t,
            f"{book}·{t}",
            f"{book}{t}",
            f"《黃帝內經{book}》",
            f"黃帝內經/{book}",
            f"黃帝內經{book}/{t}",
        ]

    for c in candidates:
        if text == c or text.startswith(c):
            if len(text) - len(c) <= 20:
                return True

    if re.match(rf"^({'|'.join(re.escape(t) for t in _title_candidates(title))}).{{0,4}}第[一二三四五六七八九十百\d]+", text):
        return True

    if len(text) <= 30 and ("…" in text or "..." in text):
        cleaned = _clean_for_match(text)
        for t in _title_candidates(title):
            if cleaned.startswith(_clean_for_match(t)[:2]):
                return True

    # 保守處理：只刪非常短且明顯是標題前綴的文字，避免誤刪內經短句。
    if len(text) <= 12:
        stripped = _clean_for_match(text)
        for t in _title_candidates(title):
            tc = _clean_for_match(t)
            if stripped and tc.startswith(stripped) and len(stripped) >= 3:
                return True

    if text in ("目錄", "編輯", "上一篇", "下一篇", "返回上一級", "返回"):
        return True

    return False


def _dedupe_keep_order(items):
    seen = set()
    result = []
    for item in items:
        key = re.sub(r"\s+", "", item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


# ─── ctext.org ──────────────────────────────────────────────────────

def fetch_ctext(slug, book="", title=""):
    """從 ctext.org 抓取指定篇章的原文。ctext 可能回傳 403，因此只作備援。"""
    urls = [
        f"{CTEXT_BASE}/{slug}/zh",
        f"{CTEXT_BASE}/{slug}",
    ]

    last_error = None
    for url in urls:
        try:
            r = SESSION.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")

            paragraphs = []
            for el in soup.select("td.ctext, .ctext"):
                text = el.get_text(separator="", strip=True)
                if not text or len(text) < 5:
                    continue
                if title and _is_title_artifact(text, book, title):
                    continue
                paragraphs.append(text)

            paragraphs = _dedupe_keep_order(paragraphs)
            if paragraphs:
                return paragraphs
        except Exception as e:
            last_error = e
            continue

    print(f"  [ctext] 失敗 {urls[0]}: {last_error}", file=sys.stderr)
    return None


# ─── wikisource ─────────────────────────────────────────────────────

def fetch_wikisource(book, title, pian_num):
    """從 zh.wikisource.org 依卷頁抓取，並只截取指定篇章。"""
    page_name = _wikisource_page_path(book, pian_num)
    if not page_name:
        print(f"  [wikisource] 找不到 {book} 篇次 {pian_num} 的卷次對應", file=sys.stderr)
        return None, None

    page_path = quote(page_name)
    url = f"{WIKISOURCE_BASE}/{page_path}"

    try:
        r = SESSION.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
    except Exception as e:
        print(f"  [wikisource] 失敗 {url}: {e}", file=sys.stderr)
        return None, None

    soup = BeautifulSoup(r.text, "html.parser")
    content = soup.find("div", class_="mw-parser-output")
    if not content:
        return None, None

    content = _extract_chapter_content(content, soup, book, title, pian_num)

    # 移除非正文元素。注意：要在截章後再移除 h2/h3，否則無法判斷章節邊界。
    junk_selectors = [
        "table", ".reference", ".references", ".noprint", ".printfooter", "#toc",
        ".mw-editsection", ".navbox", ".mw-empty-elt", ".mw-references-wrap",
        ".thumb", "style", "script", "sup.reference", "h1", "h2", "h3", "h4",
    ]
    for sel in junk_selectors:
        for el in content.select(sel):
            el.decompose()

    paragraphs, annotations = [], []
    for el in content.find_all(["p", "dl", "blockquote", "ol", "ul"], recursive=True):
        # 部分版本的校注可能藏在 small/sub/span.note 等標籤。
        for note_sel in ["small", "sub", ".note", ".gloss"]:
            for n in el.select(note_sel):
                ann = n.get_text(strip=True)
                if ann and len(ann) > 2:
                    annotations.append(ann)
                n.decompose()

        text = el.get_text(separator="", strip=True)
        text = re.sub(r"\s+", "", text)
        if not text or len(text) < 3:
            continue
        if text.startswith(("←", "→", "編輯", "目錄", "維基文庫")):
            continue
        if _is_title_artifact(text, book, title):
            continue
        paragraphs.append(text)

    paragraphs = _dedupe_keep_order(paragraphs)
    annotations = _dedupe_keep_order(annotations)

    # 品質檢查：多數內經篇章至少應有數段。至真要大論會很多段。
    if not paragraphs or sum(len(p) for p in paragraphs) < 80:
        print(f"  [wikisource] 內容過短，疑似擷取失敗：{url}", file=sys.stderr)
        return None, None

    return paragraphs, annotations or None


# ─── 格式化 ─────────────────────────────────────────────────────────

def format_chapter(book, title, pian_num, paragraphs, annotations, source):
    """產生符合本網站體例的 markdown 內容。"""
    pian_chinese = _num_to_chinese(pian_num)
    full_title = f"{title}篇第{pian_chinese}"
    lines = [
        "---",
        "tags:",
        "  - 原文",
        f"  - {book}",
        f"  - {title}",
        "---",
        "",
        f"# {book}·{full_title}",
        "",
        f"> 王冰次註本　·　來源：{source}",
        "",
        "## 篇旨",
        "",
        "> 待補（請補一段簡介本篇大要）",
        "",
        "## 原文",
        "",
    ]

    if paragraphs:
        for para in paragraphs:
            for line in para.split("\n"):
                line = line.strip()
                if line:
                    lines.append(f"> {line}")
            lines.append("")
    else:
        lines.append("> 待補")
        lines.append("")

    lines.append("## 王冰注")
    lines.append("")
    if annotations:
        for ann in annotations:
            lines.append(f"- 王冰注：{ann}")
        lines.append("")
    else:
        lines.append("> 隨原文段落附之，待補。")
        lines.append("")

    lines.append("## 註家集釋")
    lines.append("")
    lines.append("> 馬蒔、張介賓《類經》、張志聰《集註》等之擇要，待補。")
    lines.append("")

    lines.append("## 主題頁引用")
    lines.append("")
    lines.append("> 引用本篇之主題頁列表，待自動匯整。")

    return "\n".join(lines) + "\n"


# ─── 主流程 ─────────────────────────────────────────────────────────

def fetch_chapter(book, title, pian_num, slug, source_pref):
    """抓取單篇。"""
    print(f"→ {book}·{title}（篇 {pian_num}）")

    paragraphs, annotations, source = None, None, None

    if source_pref in ("auto", "wikisource"):
        paragraphs, annotations = fetch_wikisource(book, title, pian_num)
        if paragraphs:
            source = "zh.wikisource.org"
            ann_count = len(annotations or [])
            print(f"  [wikisource] {len(paragraphs)} 段，{ann_count} 條注")

    if not paragraphs and source_pref in ("auto", "ctext"):
        paragraphs = fetch_ctext(slug, book=book, title=title)
        if paragraphs:
            source = "ctext.org"
            annotations = None
            print(f"  [ctext] {len(paragraphs)} 段（無王冰注）")

    if not paragraphs:
        print("  [!] 無法取得內容")
        return None

    return format_chapter(book, title, pian_num, paragraphs, annotations, source)


def main():
    parser = argparse.ArgumentParser(description="抓取《黃帝內經》33 篇高頻引用篇")
    parser.add_argument("--chapter", help="只抓單篇（依篇名，如：至真要大論；可部分匹配）")
    parser.add_argument("--book", choices=["素問", "靈樞"], help="只抓某書")
    parser.add_argument("--source", choices=["auto", "ctext", "wikisource"], default="auto")
    parser.add_argument("--dry-run", action="store_true", help="只顯示，不寫檔")
    parser.add_argument("--delay", type=float, default=1.5, help="篇間延遲秒數")
    args = parser.parse_args()

    total_ok, total_fail, total_skip = 0, 0, 0
    for book, chapters in CHAPTERS.items():
        if args.book and args.book != book:
            continue
        for title, pian_num, slug in chapters:
            if args.chapter and args.chapter not in title:
                total_skip += 1
                continue

            content = fetch_chapter(book, title, pian_num, slug, args.source)
            if content is None:
                total_fail += 1
                continue

            target = DOCS_BASE / book / f"{title}.md"
            if args.dry_run:
                print(f"  [dry-run] 將寫入 {target}")
                print("  [dry-run] 前 500 字預覽：")
                print(content[:500])
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                print(f"  ✓ 寫入 {target}")
                total_ok += 1

            time.sleep(args.delay)

    print(f"\n完成。成功 {total_ok} 篇、失敗 {total_fail} 篇。")
    if args.chapter and total_ok == 0 and total_fail == 0:
        print(f"找不到符合 --chapter '{args.chapter}' 的篇名。")
    if total_fail:
        print("失敗篇章請手動補入，或改用 --source ctext / --source wikisource 測試。")


if __name__ == "__main__":
    main()

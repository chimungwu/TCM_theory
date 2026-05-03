"""
fetch_neijing.py
從公領域來源抓取《黃帝內經》33 篇高頻引用篇之原文，
並更新到 docs/原文/ 底下對應檔案。

來源優先順序：
  1. zh.wikisource.org（含原文與部分王冰注）
  2. ctext.org（純原文）

使用方式：
  python scripts/fetch_neijing.py                       # 抓全部 33 篇
  python scripts/fetch_neijing.py --chapter 至真要大論     # 只抓單篇
  python scripts/fetch_neijing.py --dry-run             # 只顯示不寫檔
  python scripts/fetch_neijing.py --source ctext        # 只用 ctext
  python scripts/fetch_neijing.py --source wikisource   # 只用 wikisource

需要套件：
  pip install requests beautifulsoup4
"""

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

try:
    import requests
    from bs4 import BeautifulSoup
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


CTEXT_BASE = "https://ctext.org/huangdi-neijing"
WIKISOURCE_BASE = "https://zh.wikisource.org/zh-hant"
DOCS_BASE = Path(__file__).resolve().parent.parent / "docs" / "原文"
# 用較像瀏覽器的 User-Agent，避免被簡單防爬擋掉
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}
TIMEOUT = 25


# ─── ctext.org ──────────────────────────────────────────────────────

def fetch_ctext(slug, book="", title=""):
    """從 ctext.org 抓取指定篇章的原文。

    ctext 用 td.ctext class 包裹原文段落。
    """
    url = f"{CTEXT_BASE}/{slug}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding
    except Exception as e:
        print(f"  [ctext] 失敗 {url}: {e}", file=sys.stderr)
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    paragraphs = []
    for td in soup.select("td.ctext"):
        text = td.get_text(separator="", strip=True)
        if not text or len(text) < 5:
            continue
        if title and _is_title_artifact(text, book, title):
            continue
        paragraphs.append(text)
    return paragraphs or None


# ─── wikisource ─────────────────────────────────────────────────────

def _is_title_artifact(text, book, title):
    """判斷某段文字是否只是頁面標題／導覽／節錨點，應排除。"""
    text = text.strip()
    if len(text) > 60:
        return False  # 真正內容通常較長

    # 篇名相關之前綴
    candidates = [
        title,
        f"{book}·{title}",
        f"{book}{title}",
        f"《黃帝內經{book}》",
        f"黃帝內經·{book}",
        f"黃帝內經 {book}",
        f"黃帝內經{book}",
        f"黃帝內經{book}/{title}",
    ]
    for c in candidates:
        if text == c or text.startswith(c):
            if len(text) - len(c) <= 20:
                return True

    # 篇次格式：如「至真要大論篇第七十四」
    if re.match(rf"^{re.escape(title)}.{{0,2}}第[一二三四五六七八九十百\d]+", text):
        return True

    # 截斷式錨點：「至真要大... :」「至真要大論…」之類
    # 規則：短文字（≤30 字）含 "..." 或 "…"，且前綴與篇名匹配 ≥2 字
    if len(text) <= 30 and ("…" in text or "..." in text):
        common = 0
        for i, ch in enumerate(text):
            if i < len(title) and ch == title[i]:
                common = i + 1
            else:
                break
        if common >= 2:
            return True

    # 短文字（≤20 字）且只剩標點與標題前綴
    if len(text) <= 20:
        # 移除所有標點與空白後，剩下與篇名前綴重合
        stripped = re.sub(r"[\s\.\:：。，,…\-—《》「」『』（）()【】\[\]\"']+", "", text)
        common = 0
        for i, ch in enumerate(stripped):
            if i < len(title) and ch == title[i]:
                common = i + 1
            else:
                break
        if common >= 3 and common >= len(stripped):
            return True

    # 純導覽詞
    if text in ("目錄", "編輯", "上一篇", "下一篇", "返回上一級", "返回"):
        return True

    return False


def fetch_wikisource(book, title):
    """從 zh.wikisource.org 抓取（含原文，注少見）。

    URL 格式：https://zh.wikisource.org/zh-hant/黃帝內經素問/上古天真論
    """
    page_path = quote(f"黃帝內經{book}/{title}")
    url = f"{WIKISOURCE_BASE}/{page_path}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
    except Exception as e:
        print(f"  [wikisource] 失敗 {url}: {e}", file=sys.stderr)
        return None, None

    soup = BeautifulSoup(r.text, "html.parser")
    content = soup.find("div", class_="mw-parser-output")
    if not content:
        return None, None

    # 移除非內容元素
    junk_selectors = [
        "table", ".reference", ".noprint", ".printfooter", "#toc",
        ".mw-editsection", ".navbox", ".mw-empty-elt",
        ".mw-references-wrap", ".thumb", "h1", "h2", "h3",
    ]
    for sel in junk_selectors:
        for el in content.select(sel):
            el.decompose()

    # 段落收集
    paragraphs, annotations = [], []
    for el in content.find_all(["p", "dl", "blockquote", "ol", "ul"], recursive=True):
        # 內嵌的 <small>、<dd>、註腳——可能是王冰注
        for note_sel in ["small", "sub", ".note", ".gloss"]:
            for n in el.select(note_sel):
                ann = n.get_text(strip=True)
                if ann and len(ann) > 2:
                    annotations.append(ann)
                n.decompose()  # 從段落中移除，避免重複出現在原文

        text = el.get_text(separator="", strip=True)
        if not text or len(text) < 3:
            continue
        if text.startswith(("←", "→", "編輯", "目錄")):
            continue
        if _is_title_artifact(text, book, title):
            continue

        paragraphs.append(text)

    return paragraphs or None, annotations or None


# ─── 格式化 ─────────────────────────────────────────────────────────

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
            # 每段以 blockquote 呈現
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
        paragraphs, annotations = fetch_wikisource(book, title)
        if paragraphs:
            source = "zh.wikisource.org"
            ann_count = len(annotations or [])
            print(f"  [wikisource] {len(paragraphs)} 段，{ann_count} 條注")

    if not paragraphs and source_pref in ("auto", "ctext"):
        paragraphs = fetch_ctext(slug, book=book, title=title)
        if paragraphs:
            source = "ctext.org"
            print(f"  [ctext] {len(paragraphs)} 段（無王冰注）")

    if not paragraphs:
        print(f"  [!] 無法取得內容")
        return None

    return format_chapter(book, title, pian_num, paragraphs, annotations, source)


def main():
    parser = argparse.ArgumentParser(description="抓取《黃帝內經》33 篇高頻引用篇")
    parser.add_argument("--chapter", help="只抓單篇（依篇名，如：至真要大論）")
    parser.add_argument("--book", choices=["素問", "靈樞"], help="只抓某書")
    parser.add_argument("--source", choices=["auto", "ctext", "wikisource"], default="auto")
    parser.add_argument("--dry-run", action="store_true", help="只顯示，不寫檔")
    parser.add_argument("--delay", type=float, default=2.0, help="篇間延遲秒數")
    args = parser.parse_args()

    total_ok, total_fail = 0, 0
    for book, chapters in CHAPTERS.items():
        if args.book and args.book != book:
            continue
        for title, pian_num, slug in chapters:
            if args.chapter and args.chapter != title:
                continue

            content = fetch_chapter(book, title, pian_num, slug, args.source)
            if content is None:
                total_fail += 1
                continue

            target = DOCS_BASE / book / f"{title}.md"
            if args.dry_run:
                print(f"  [dry-run] 將寫入 {target}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                print(f"  ✓ 寫入 {target}")
                total_ok += 1

            time.sleep(args.delay)

    print(f"\n完成。成功 {total_ok} 篇、失敗 {total_fail} 篇。")
    if total_fail:
        print("失敗篇章請手動補入，或試其他來源。")


if __name__ == "__main__":
    main()

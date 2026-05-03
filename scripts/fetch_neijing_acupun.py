#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fetch_neijing_acupun.py

從 acupun.site 抓取《黃帝內經》原文，整理成本站 docs/原文/ 的 Markdown 格式。

重點：
  - 只保留古籍原文
  - 自動排除【翻譯】、【陳擎文補註】與其後續說明段落
  - 輸出符合 docs/原文/index.md 的格式

使用方式：
  python scripts/fetch_neijing_acupun.py --highfreq --dry-run
  python scripts/fetch_neijing_acupun.py --highfreq
  python scripts/fetch_neijing_acupun.py --chapter 至真要大論 --dry-run
  python scripts/fetch_neijing_acupun.py --chapter 經脈 --book 靈樞
  python scripts/fetch_neijing_acupun.py --list

需要套件：
  pip install requests beautifulsoup4
"""

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("缺少套件。請先執行：pip install requests beautifulsoup4")
    sys.exit(1)


BASE = "https://acupun.site/"
SUWEN_INDEX = "https://acupun.site/huangdineijingsuwen.aspx"
LINGSHU_INDEX = "https://acupun.site/huangdineijinglingshu24.aspx"

DOCS_BASE = Path(__file__).resolve().parent.parent / "docs" / "原文"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

TIMEOUT = 25

HIGH_FREQ = {
    "素問": [
        "上古天真論", "生氣通天論", "陰陽應象大論", "靈蘭秘典論",
        "六節藏象論", "五臟生成", "五臟別論", "脈要精微論",
        "經脈別論", "宣明五氣", "太陰陽明論", "熱論", "瘧論",
        "咳論", "舉痛論", "風論", "痺論", "痿論", "厥論", "奇病論",
        "骨空論", "水熱穴論", "調經論", "六元正紀大論", "至真要大論",
    ],
    "靈樞": [
        "本神", "經脈", "營衛生會", "癲狂", "決氣", "海論", "五味", "百病始生",
    ],
}

SECTION_MARKERS_TO_SKIP = [
    "【翻譯】", "【譯文】", "【白話】", "【解釋】", "【說明】", "【語譯】", "【今譯】",
    "【陳擎文補註】", "【陳擎文補注】", "陳擎文補註", "陳擎文補注",
]


def get_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def clean_title(raw: str) -> tuple[int | None, str]:
    text = re.sub(r"\s+", "", raw)
    m = re.match(r"^(\d{1,3})[\.．、]?(.*)$", text)
    if not m:
        return None, text
    num = int(m.group(1))
    title = m.group(2).strip()
    title = re.sub(r"[　\s]+", "", title)
    title = title.strip("｜|：:。")
    return num, title


def discover_chapters(book: str) -> dict[str, dict]:
    if book == "素問":
        index_url = SUWEN_INDEX
        prefix = "suwen"
    elif book == "靈樞":
        index_url = LINGSHU_INDEX
        prefix = "lingshu"
    else:
        raise ValueError("book 必須是 素問 或 靈樞")

    html = get_html(index_url)
    soup = BeautifulSoup(html, "html.parser")
    chapters = {}

    for a in soup.find_all("a", href=True):
        href = a["href"]
        label = a.get_text(strip=True)

        if not re.search(rf"{prefix}\d+\.html$", href):
            continue

        num, title = clean_title(label)
        if not num or not title:
            continue

        chapters[title] = {
            "book": book,
            "num": num,
            "url": urljoin(BASE, href),
        }

    return chapters


def build_catalog() -> dict[str, dict]:
    catalog = {}
    for book in ["素問", "靈樞"]:
        try:
            catalog.update(discover_chapters(book))
        except Exception as e:
            print(f"[!] 讀取{book}目錄失敗：{e}", file=sys.stderr)
    return catalog


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_noise(text: str) -> bool:
    noise_keywords = [
        "再探針灸大成", "關於我們", "最新消息",
        "黃帝內經•原文檢索", "黃帝內經·原文檢索",
        "無壓力閱讀版", "大中小", "上一篇", "下一篇", "返回", "目錄",
        "Copyright", "版權", "網站", "搜尋", "下載", "手機版", "繁體", "簡體",
    ]

    if not text:
        return True
    if len(text) <= 2:
        return True
    if any(k in text for k in noise_keywords):
        return True
    if re.fullmatch(r"[\s\-\*_=—─]+", text):
        return True
    return False


def is_skip_marker(text: str) -> bool:
    if any(marker in text for marker in SECTION_MARKERS_TO_SKIP):
        return True
    if re.fullmatch(r"【[^】]{1,20}】", text):
        return True
    return False


def is_likely_original_text(text: str) -> bool:
    modern_words = [
        "意思是", "這是說", "也就是", "現代", "我們", "可以看出", "簡單來說",
        "所謂", "例如", "臨床", "治療", "疾病", "症狀", "患者", "醫師",
        "說明", "解釋", "翻譯", "白話",
    ]
    if any(w in text for w in modern_words):
        return False

    classic_patterns = [
        r"黃帝", r"岐伯", r"雷公", r"少師", r"伯高", r"帝曰", r"問曰",
        r"曰：", r"曰:", r"故曰", r"是謂", r"奈何", r"何謂", r"願聞",
    ]

    if any(re.search(p, text) for p in classic_patterns):
        return True

    if len(text) >= 8 and re.search(r"[也矣焉乎者。；]$", text):
        return True

    return False


def parse_article(html: str, title: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "header", "footer", "iframe", "form"]):
        tag.decompose()

    strings = [normalize_text(s) for s in soup.stripped_strings]

    paragraphs = []
    seen = set()
    started = False
    skip_mode = False

    for s in strings:
        if is_noise(s):
            continue

        if title in s and len(s) <= len(title) + 30:
            continue

        if is_skip_marker(s):
            skip_mode = True
            continue

        if not started:
            if is_likely_original_text(s):
                started = True
                skip_mode = False
            else:
                continue

        if skip_mode:
            if is_likely_original_text(s):
                skip_mode = False
            else:
                continue

        if not is_likely_original_text(s):
            continue

        if len(s) < 4:
            continue

        if s not in seen:
            paragraphs.append(s)
            seen.add(s)

    return paragraphs


def format_markdown(book: str, title: str, num: int, paragraphs: list[str], source_url: str) -> str:
    lines = [
        "---",
        "tags:",
        "  - 原文",
        f"  - {book}",
        f"  - {title}",
        "---",
        "",
        f"# {book}·{title}",
        "",
        f"> 王冰次註本·篇 {num}",
        "",
        "<!--",
        f"原文來源：{source_url}",
        "說明：抓取時已排除翻譯、白話解釋與現代補註；本站體例仍以王冰次註本架構整理。",
        "-->",
        "",
        "## 篇旨",
        "",
        "> 待補（請補一段簡介本篇大要）",
        "",
        "## 原文",
        "",
    ]

    if paragraphs:
        for p in paragraphs:
            lines.append(f"> {p}")
            lines.append("")
    else:
        lines.append("> 待補")
        lines.append("")

    lines += [
        "## 王冰注",
        "",
        "> 待補。",
        "",
        "## 註家集釋",
        "",
        "> 馬蒔、張介賓《類經》、張志聰《集註》等之擇要，待補。",
        "",
        "## 主題頁引用",
        "",
        "> 引用本篇之主題頁列表，待自動匯整。",
        "",
    ]

    return "\n".join(lines)


def fetch_one(item: dict, dry_run: bool = False) -> bool:
    book = item["book"]
    title = item["title"]
    num = item["num"]
    url = item["url"]

    print(f"→ {book}·{title}（篇 {num}）")

    try:
        html = get_html(url)
        paragraphs = parse_article(html, title)
    except Exception as e:
        print(f"  [!] 失敗：{e}", file=sys.stderr)
        return False

    if not paragraphs:
        print("  [!] 沒抓到正文段落")
        return False

    print(f"  ✓ 抓到 {len(paragraphs)} 段")

    md = format_markdown(book, title, num, paragraphs, url)
    target = DOCS_BASE / book / f"{title}.md"

    if dry_run:
        print(f"  [dry-run] 將寫入 {target}")
        print("  預覽前 5 段：")
        for p in paragraphs[:5]:
            print(f"    - {p[:120]}")
        return True

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(md, encoding="utf-8")
    print(f"  ✓ 寫入 {target}")
    return True


def make_tasks_from_highfreq(catalog: dict[str, dict]) -> list[dict]:
    tasks = []
    for book, titles in HIGH_FREQ.items():
        for title in titles:
            item = catalog.get(title)
            if item and item["book"] == book:
                tasks.append(dict(item, title=title))
            else:
                print(f"[!] 高頻篇章找不到：{book}·{title}", file=sys.stderr)

    tasks.sort(key=lambda x: (0 if x["book"] == "素問" else 1, x["num"]))
    return tasks


def main():
    parser = argparse.ArgumentParser(
        description="從 acupun.site 抓取《黃帝內經》素問/靈樞原文，排除翻譯與現代補註。"
    )
    parser.add_argument("--chapter", help="只抓單篇，如：至真要大論、經脈、決氣")
    parser.add_argument("--book", choices=["素問", "靈樞"], help="指定書名，避免同名篇章混淆")
    parser.add_argument("--highfreq", action="store_true", help="抓第一階段高頻 33 篇")
    parser.add_argument("--all", action="store_true", help="抓指定書全部篇章，需搭配 --book")
    parser.add_argument("--list", action="store_true", help="列出目前從網站目錄抓到的篇章")
    parser.add_argument("--dry-run", action="store_true", help="只顯示，不寫檔")
    parser.add_argument("--delay", type=float, default=1.0, help="篇間延遲秒數")
    args = parser.parse_args()

    catalog = build_catalog()

    if not catalog:
        print("[!] 無法建立篇章目錄")
        sys.exit(1)

    if args.list:
        for book in ["素問", "靈樞"]:
            print(f"\n[{book}]")
            rows = sorted(
                [dict(v, title=k) for k, v in catalog.items() if v["book"] == book],
                key=lambda x: x["num"],
            )
            for v in rows:
                print(f"{v['num']:02d}. {v['title']} -> {v['url']}")
        return

    tasks = []

    if args.highfreq:
        tasks = make_tasks_from_highfreq(catalog)

    elif args.chapter:
        matches = [
            dict(v, title=k)
            for k, v in catalog.items()
            if args.chapter == k or args.chapter in k
        ]

        if args.book:
            matches = [m for m in matches if m["book"] == args.book]

        if not matches:
            print(f"[!] 找不到篇章：{args.chapter}")
            print("可先執行：python scripts/fetch_neijing_acupun.py --list")
            sys.exit(1)

        if len(matches) > 1:
            print("[!] 找到多個相似篇章，請加 --book 或輸入完整篇名：")
            for m in matches:
                print(f"  - {m['book']} {m['num']:02d}. {m['title']}")
            sys.exit(1)

        tasks = matches

    elif args.all:
        if not args.book:
            print("[!] --all 需搭配 --book 素問 或 --book 靈樞")
            sys.exit(1)

        tasks = [
            dict(v, title=k)
            for k, v in catalog.items()
            if v["book"] == args.book
        ]
        tasks.sort(key=lambda x: x["num"])

    else:
        parser.print_help()
        return

    ok = 0
    fail = 0

    for item in tasks:
        if fetch_one(item, dry_run=args.dry_run):
            ok += 1
        else:
            fail += 1
        time.sleep(args.delay)

    print(f"\n完成。成功 {ok} 篇、失敗 {fail} 篇。")


if __name__ == "__main__":
    main()

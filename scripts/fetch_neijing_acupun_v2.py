#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fetch_neijing_acupun.py

從 acupun.site「黃帝內經無壓力閱讀版」抓取《素問》《靈樞》篇章，
整理成 Markdown，寫入 docs/原文/素問 或 docs/原文/靈樞。

使用方式：
  python scripts/fetch_neijing_acupun.py --chapter 至真要大論
  python scripts/fetch_neijing_acupun.py --chapter 經脈
  python scripts/fetch_neijing_acupun.py --book 素問 --all
  python scripts/fetch_neijing_acupun.py --book 靈樞 --all
  python scripts/fetch_neijing_acupun.py --highfreq
  python scripts/fetch_neijing_acupun.py --list
  python scripts/fetch_neijing_acupun.py --chapter 至真要大論 --dry-run

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

# 你原本規劃的 33 篇高頻引用篇
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


def get_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def clean_title(raw: str) -> tuple[int | None, str]:
    """
    將「74.至真要大論」「10.經脈」轉成 (74, "至真要大論")
    """
    text = re.sub(r"\s+", "", raw)
    m = re.match(r"^(\d{1,2})[\.．、]?(.*)$", text)
    if not m:
        return None, text
    num = int(m.group(1))
    title = m.group(2).strip()
    return num, title


def discover_chapters(book: str) -> dict[str, dict]:
    """
    從目錄頁自動抓篇名與連結。
    回傳：
      {
        "至真要大論": {"book": "素問", "num": 74, "url": ".../suwen74.html"},
        ...
      }
    """
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

        # 只取 huangdineijing/suwenXX.html 或 huangdineijing/lingshuXX.html
        if not re.search(rf"{prefix}\d+\.html$", href):
            continue

        num, title = clean_title(label)
        if not num or not title:
            continue

        url = urljoin(BASE, href)
        chapters[title] = {
            "book": book,
            "num": num,
            "url": url,
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


def is_noise(text: str) -> bool:
    noise_keywords = [
        "再探針灸大成",
        "關於我們",
        "最新消息",
        "黃帝內經•原文檢索",
        "無壓力閱讀版",
        "大中小",
        "上一篇",
        "下一篇",
        "返回",
        "目錄",
        "Copyright",
        "版權",
        "網站",
        "搜尋",
        "下載",
    ]
    if not text:
        return True
    if len(text) <= 2:
        return True
    if any(k in text for k in noise_keywords):
        return True
    # 過濾純符號
    if re.fullmatch(r"[\s\-\*_=—─]+", text):
        return True
    return False


def parse_article(html: str, title: str) -> list[str]:
    """
    acupun 單篇頁面正文多半直接散在 body text node 中；
    BeautifulSoup 取 stripped_strings 最穩。
    """
    soup = BeautifulSoup(html, "html.parser")

    # 移除導覽、script、style 等
    for tag in soup(["script", "style", "nav", "header", "footer", "iframe"]):
        tag.decompose()

    strings = [s.strip() for s in soup.stripped_strings]
    paragraphs = []

    started = False
    for s in strings:
        s = re.sub(r"\s+", " ", s).strip()
        if is_noise(s):
            continue

        # 跳過標題列
        if title in s and ("黃帝內經" in s or "無壓力閱讀版" in s):
            started = True
            continue

        # 多數正文從「黃帝」「岐伯」「雷公」「少師」等問答開始
        if not started:
            if re.search(r"(黃帝|岐伯|雷公|少師|伯高|帝曰|問曰|曰：)", s):
                started = True
            else:
                continue

        if started:
            # 排除太短的 anchor/章節小標
            if len(s) < 4:
                continue
            paragraphs.append(s)

    # 去重，保留順序
    clean = []
    seen = set()
    for p in paragraphs:
        if p not in seen:
            clean.append(p)
            seen.add(p)

    return clean


def num_to_chinese(n: int) -> str:
    chars = "零一二三四五六七八九"
    if n < 10:
        return chars[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + chars[n - 10]
    tens, ones = divmod(n, 10)
    return chars[tens] + "十" + (chars[ones] if ones else "")


def format_markdown(book: str, title: str, num: int, paragraphs: list[str], source_url: str) -> str:
    lines = [
        "---",
        "tags:",
        "  - 原文",
        f"  - {book}",
        f"  - {title}",
        "---",
        "",
        f"# {book}·{title}篇第{num_to_chinese(num)}",
        "",
        f"> 來源：acupun.site　·　原始連結：{source_url}",
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
        print("  預覽前 3 段：")
        for p in paragraphs[:3]:
            print(f"    - {p[:80]}")
        return True

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(md, encoding="utf-8")
    print(f"  ✓ 寫入 {target}")
    return True


def main():
    parser = argparse.ArgumentParser(description="從 acupun.site 抓取《黃帝內經》素問/靈樞原文")
    parser.add_argument("--chapter", help="只抓單篇，如：至真要大論、經脈、決氣")
    parser.add_argument("--book", choices=["素問", "靈樞"], help="指定書名")
    parser.add_argument("--all", action="store_true", help="抓指定書名全部篇章，需搭配 --book")
    parser.add_argument("--highfreq", action="store_true", help="抓 33 篇高頻引用篇")
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
                [v for v in catalog.values() if v["book"] == book],
                key=lambda x: x["num"],
            )
            for v in rows:
                print(f"{v['num']:02d}. {v['title']} -> {v['url']}")
        return

    tasks = []

    if args.chapter:
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

    elif args.highfreq:
        for book, titles in HIGH_FREQ.items():
            for title in titles:
                if title in catalog and catalog[title]["book"] == book:
                    tasks.append(dict(catalog[title], title=title))
                else:
                    print(f"[!] 高頻篇章找不到：{book}·{title}", file=sys.stderr)
        tasks.sort(key=lambda x: (x["book"], x["num"]))

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

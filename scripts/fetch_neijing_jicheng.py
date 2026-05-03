#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fetch_neijing_jicheng.py

從 jicheng.tw 抓取《黃帝內經素問》與《靈樞》全文 index.html，
依篇章標題切出本站第一階段高頻 33 篇，輸出到 docs/原文/。

資料源：
  素問：https://jicheng.tw/tcm/book/黃帝內經素問/index.html
  靈樞：https://jicheng.tw/tcm/book/靈樞/index.html

特點：
  - jicheng 是整本書單頁全文，不是一篇一頁
  - 本程式會依「上古天真論篇第一」「本神第八」等標題切篇
  - 只輸出原文，不抓翻譯、不抓現代補註
  - Markdown 格式符合 docs/原文/index.md

使用方式：
  python scripts/fetch_neijing_jicheng.py --list
  python scripts/fetch_neijing_jicheng.py --highfreq --dry-run
  python scripts/fetch_neijing_jicheng.py --highfreq
  python scripts/fetch_neijing_jicheng.py --chapter 至真要大論 --dry-run
  python scripts/fetch_neijing_jicheng.py --chapter 經脈 --book 靈樞
  python scripts/fetch_neijing_jicheng.py --book 素問 --all --dry-run

需要套件：
  pip install requests beautifulsoup4
"""

import argparse
import re
import sys
import time
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("缺少套件。請先執行：pip install requests beautifulsoup4")
    sys.exit(1)


URLS = {
    "素問": "https://jicheng.tw/tcm/book/%E9%BB%83%E5%B8%9D%E5%85%A7%E7%B6%93%E7%B4%A0%E5%95%8F/index.html",
    "靈樞": "https://jicheng.tw/tcm/book/%E9%9D%88%E6%A8%9E/index.html",
}

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
        "上古天真論",
        "生氣通天論",
        "陰陽應象大論",
        "靈蘭秘典論",
        "六節藏象論",
        "五臟生成",
        "五臟別論",
        "脈要精微論",
        "經脈別論",
        "宣明五氣",
        "太陰陽明論",
        "熱論",
        "瘧論",
        "咳論",
        "舉痛論",
        "風論",
        "痺論",
        "痿論",
        "厥論",
        "奇病論",
        "骨空論",
        "水熱穴論",
        "調經論",
        "六元正紀大論",
        "至真要大論",
    ],
    "靈樞": [
        "本神",
        "經脈",
        "營衛生會",
        "癲狂",
        "決氣",
        "海論",
        "五味",
        "百病始生",
    ],
}

CHINESE_NUM = "〇零一二三四五六七八九十百"


def get_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chinese_num_to_int(s: str) -> int | None:
    """
    中文數字轉整數，支援一到一百六十二左右即可。
    例：第一、七十四、百病始生不會送進來。
    """
    s = s.strip().replace("第", "")
    digit = {
        "〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    }

    if not s:
        return None

    if s.isdigit():
        return int(s)

    total = 0

    if "百" in s:
        before, after = s.split("百", 1)
        total += (digit.get(before, 1) if before else 1) * 100
        s = after

    if "十" in s:
        before, after = s.split("十", 1)
        total += (digit.get(before, 1) if before else 1) * 10
        if after:
            total += digit.get(after, 0)
        return total

    if s in digit:
        return digit[s]

    return total or None


def parse_heading(line: str, book: str) -> tuple[str, int] | None:
    """
    判斷一行是否為篇章標題。

    素問常見：
      上古天真論篇第一
      至真要大論篇第七十四

    靈樞常見：
      九鍼十二原第一
      本神第八
      經脈第十
    """
    line = normalize_text(line)
    if not line:
        return None

    # 避免正文長句誤判
    if len(line) > 30:
        return None

    if book == "素問":
        m = re.match(r"^(.+?)篇第([" + CHINESE_NUM + r"\d]+)$", line)
    else:
        m = re.match(r"^(.+?)第([" + CHINESE_NUM + r"\d]+)$", line)

    if not m:
        return None

    title = m.group(1).strip()
    num_text = m.group(2).strip()
    num = chinese_num_to_int(num_text)

    if not title or not num:
        return None

    # 過濾卷名、序文等
    if title.startswith("卷") or title in ("序",):
        return None

    return title, num


def extract_text_lines(html: str) -> list[str]:
    """
    取出頁面文字行。

    jicheng 的頁面由標題與段落組成；用 stripped_strings 可保留 h2/p 的順序。
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "header", "footer", "iframe", "form"]):
        tag.decompose()

    lines = []
    for s in soup.stripped_strings:
        text = normalize_text(s)
        if text:
            lines.append(text)

    return lines


def split_book(book: str, html: str) -> dict[str, dict]:
    """
    把整本書切成篇章。

    回傳：
      {
        "至真要大論": {
          "book": "素問",
          "num": 74,
          "paragraphs": [...]
        }
      }
    """
    lines = extract_text_lines(html)
    chapters = {}

    current_title = None
    current_num = None
    current_paragraphs = []

    def save_current():
        nonlocal current_title, current_num, current_paragraphs
        if current_title and current_num and current_paragraphs:
            # 去重但保序
            seen = set()
            clean = []
            for p in current_paragraphs:
                if p not in seen:
                    clean.append(p)
                    seen.add(p)

            chapters[current_title] = {
                "book": book,
                "num": current_num,
                "paragraphs": clean,
            }

    for line in lines:
        heading = parse_heading(line, book)

        if heading:
            save_current()
            current_title, current_num = heading
            current_paragraphs = []
            continue

        if current_title:
            if is_content_noise(line):
                continue
            current_paragraphs.append(line)

    save_current()
    return chapters


def is_content_noise(text: str) -> bool:
    """
    過濾頁面導覽、書籍 metadata、空泛標籤。
    jicheng 本身較乾淨，這裡只做保守清理。
    """
    if not text or len(text) <= 1:
        return True

    noise_keywords = [
        "中醫笈成",
        "典籍",
        "作者",
        "朝代",
        "年份",
        "底本",
        "品質",
        "美國國會圖書館藏本",
        "Copyright",
        "版權",
    ]

    if any(k in text for k in noise_keywords):
        return True

    if re.match(r"^卷第", text):
        return True

    if re.fullmatch(r"[\s\-\*_=—─]+", text):
        return True

    return False


def build_catalog() -> dict[str, dict]:
    """
    抓素問與靈樞全文，切成篇章。
    """
    catalog = {}

    for book, url in URLS.items():
        print(f"[讀取] {book}：{url}")
        html = get_html(url)
        chapters = split_book(book, html)

        for title, item in chapters.items():
            item["title"] = title
            item["source_url"] = url
            catalog[(book, title)] = item

        print(f"  ✓ {book} 切出 {len(chapters)} 篇")

    return catalog


def format_markdown(item: dict) -> str:
    book = item["book"]
    title = item["title"]
    num = item["num"]
    paragraphs = item["paragraphs"]
    source_url = item["source_url"]

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
        "說明：jicheng.tw 為整本書全文頁；本檔由程式依篇章標題切出。",
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


def write_item(item: dict, dry_run: bool = False) -> bool:
    book = item["book"]
    title = item["title"]
    num = item["num"]
    paragraphs = item["paragraphs"]

    print(f"→ {book}·{title}（篇 {num}）")

    if not paragraphs:
        print("  [!] 沒有正文")
        return False

    target = DOCS_BASE / book / f"{title}.md"

    if dry_run:
        print(f"  [dry-run] 將寫入 {target}")
        print(f"  ✓ 段落數：{len(paragraphs)}")
        print("  預覽前 3 段：")
        for p in paragraphs[:3]:
            print(f"    - {p[:120]}")
        return True

    md = format_markdown(item)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(md, encoding="utf-8")
    print(f"  ✓ 寫入 {target}（{len(paragraphs)} 段）")
    return True


def select_tasks(catalog: dict[tuple[str, str], dict], args) -> list[dict]:
    tasks = []

    if args.highfreq:
        for book, titles in HIGH_FREQ.items():
            for title in titles:
                item = catalog.get((book, title))
                if item:
                    tasks.append(item)
                else:
                    print(f"[!] 高頻篇章找不到：{book}·{title}", file=sys.stderr)

    elif args.chapter:
        matches = []

        for (book, title), item in catalog.items():
            if args.book and book != args.book:
                continue
            if args.chapter == title or args.chapter in title:
                matches.append(item)

        if not matches:
            print(f"[!] 找不到篇章：{args.chapter}")
            sys.exit(1)

        if len(matches) > 1:
            print("[!] 找到多個相似篇章，請加 --book 或輸入完整篇名：")
            for item in matches:
                print(f"  - {item['book']} {item['num']:02d}. {item['title']}")
            sys.exit(1)

        tasks = matches

    elif args.all:
        if not args.book:
            print("[!] --all 需搭配 --book 素問 或 --book 靈樞")
            sys.exit(1)

        tasks = [
            item for (book, title), item in catalog.items()
            if book == args.book
        ]

    else:
        return []

    tasks.sort(key=lambda x: (0 if x["book"] == "素問" else 1, x["num"]))
    return tasks


def main():
    parser = argparse.ArgumentParser(
        description="從 jicheng.tw 抓取《黃帝內經素問》《靈樞》全文，依篇章切出 Markdown。"
    )
    parser.add_argument("--chapter", help="只抓單篇，如：至真要大論、經脈、決氣")
    parser.add_argument("--book", choices=["素問", "靈樞"], help="指定書名")
    parser.add_argument("--highfreq", action="store_true", help="抓第一階段高頻 33 篇")
    parser.add_argument("--all", action="store_true", help="抓指定書全部篇章，需搭配 --book")
    parser.add_argument("--list", action="store_true", help="列出切出的篇章")
    parser.add_argument("--dry-run", action="store_true", help="只顯示，不寫檔")
    parser.add_argument("--delay", type=float, default=0.5, help="篇間延遲秒數")
    args = parser.parse_args()

    catalog = build_catalog()

    if args.list:
        for book in ["素問", "靈樞"]:
            print(f"\n[{book}]")
            rows = sorted(
                [item for (b, _), item in catalog.items() if b == book],
                key=lambda x: x["num"],
            )
            for item in rows:
                print(f"{item['num']:02d}. {item['title']}（{len(item['paragraphs'])} 段）")
        return

    tasks = select_tasks(catalog, args)

    if not tasks:
        parser.print_help()
        return

    ok = 0
    fail = 0

    for item in tasks:
        if write_item(item, dry_run=args.dry_run):
            ok += 1
        else:
            fail += 1

        time.sleep(args.delay)

    print(f"\n完成。成功 {ok} 篇、失敗 {fail} 篇。")


if __name__ == "__main__":
    main()

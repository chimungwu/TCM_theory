#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fetch_neijing_jicheng_list.py

從 jicheng.tw「條列版」抓取《黃帝內經素問》與《靈樞》原文，
切出本站第一階段高頻 33 篇，輸出到 docs/原文/。

資料源：
  素問條列版：
    https://jicheng.tw/tcm/book/黃帝內經素問_條列版/index.html
  靈樞條列版：
    https://jicheng.tw/tcm/book/靈樞_條列版/index.html

特點：
  - 使用條列版，保留來源標點與段落
  - 只抓「本文」欄位，不抓翻譯、不抓現代補註
  - 依「書名、篇名、篇次、本文」欄位解析
  - 輸出符合 docs/原文/index.md 的 Markdown 格式

使用方式：
  python scripts/fetch_neijing_jicheng_list.py --list
  python scripts/fetch_neijing_jicheng_list.py --highfreq --dry-run
  python scripts/fetch_neijing_jicheng_list.py --highfreq
  python scripts/fetch_neijing_jicheng_list.py --chapter 上古天真論 --dry-run
  python scripts/fetch_neijing_jicheng_list.py --chapter 經脈 --book 靈樞
  python scripts/fetch_neijing_jicheng_list.py --book 素問 --all --dry-run

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
    "素問": "https://jicheng.tw/tcm/book/%E9%BB%83%E5%B8%9D%E5%85%A7%E7%B6%93%E7%B4%A0%E5%95%8F_%E6%A2%9D%E5%88%97%E7%89%88/index.html",
    "靈樞": "https://jicheng.tw/tcm/book/%E9%9D%88%E6%A8%9E_%E6%A2%9D%E5%88%97%E7%89%88/index.html",
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

# 第一階段：高頻引用 33 篇
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

SPEAKER_PATTERNS = [
    "黃帝問曰：",
    "黃帝曰：",
    "帝曰：",
    "岐伯對曰：",
    "岐伯曰：",
    "歧伯對曰：",
    "歧伯曰：",
    "雷公問曰：",
    "雷公曰：",
    "少師曰：",
    "伯高曰：",
]


def get_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def normalize_text(text: str) -> str:
    """
    保留中文標點，只清理空白。
    """
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return text.strip()


def strip_field_label(line: str) -> tuple[str | None, str]:
    """
    解析「欄位：內容」。
    支援：
      篇名：上古天真論
      本文：昔在黃帝，生而神靈...
      篇次：1
    """
    line = normalize_text(line)
    m = re.match(r"^([^：:]{1,12})[：:](.*)$", line)
    if not m:
        return None, line
    key = m.group(1).strip()
    value = m.group(2).strip()
    return key, value


def extract_lines(html: str) -> list[str]:
    """
    條列版頁面通常是大量「欄位：內容」文字。
    用 get_text("\\n") 保留標點與換行，比 stripped_strings 穩。
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "header", "footer", "iframe", "form"]):
        tag.decompose()

    raw = soup.get_text("\n")
    lines = []

    for line in raw.split("\n"):
        line = normalize_text(line)
        if line:
            lines.append(line)

    return lines


def is_page_noise(line: str) -> bool:
    if not line:
        return True

    noise_keywords = [
        "中醫笈成",
        "典籍",
        "書名",
        "作者",
        "朝代",
        "年份",
        "底本",
        "品質",
        "美國國會圖書館藏本",
        "Copyright",
        "版權",
        "首頁",
        "搜尋",
    ]

    if line in ("上一頁", "下一頁", "返回", "目錄"):
        return True

    if any(k in line for k in noise_keywords):
        return True

    if re.fullmatch(r"[\s\-\*_=—─]+", line):
        return True

    return False


def normalize_title(title: str) -> str:
    """
    清理篇名。
    """
    title = normalize_text(title)
    title = re.sub(r"^黃帝內經[素問靈樞]*", "", title)
    title = title.replace("篇", "")
    title = title.strip(" 　：:。")
    return title


def parse_num(value: str) -> int | None:
    value = normalize_text(value)
    m = re.search(r"\d+", value)
    if m:
        return int(m.group(0))
    return chinese_num_to_int(value)


def chinese_num_to_int(s: str) -> int | None:
    s = s.strip().replace("第", "").replace("篇", "")
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


def split_by_speaker(text: str) -> list[str]:
    """
    將單篇本文依問答標記切成較自然段落。
    若來源已經分段，後面會保留；若一大段，這裡會切開。

    注意：不新增標點，只利用來源已有「曰：」等標記。
    """
    text = normalize_text(text)
    if not text:
        return []

    # 在問答標記前插入切分記號
    markers = sorted(SPEAKER_PATTERNS, key=len, reverse=True)

    for marker in markers:
        text = text.replace(marker, "\n" + marker)

    parts = []
    for part in text.split("\n"):
        part = normalize_text(part)
        if part:
            parts.append(part)

    return parts


def clean_paragraphs(paragraphs: list[str]) -> list[str]:
    """
    去重、去雜訊、去空段。
    """
    clean = []
    seen = set()

    for p in paragraphs:
        p = normalize_text(p)

        if not p:
            continue
        if is_page_noise(p):
            continue

        # 避免欄位殘留
        key, value = strip_field_label(p)
        if key in ("篇名", "篇次", "書名", "作者", "朝代", "年份", "底本", "品質"):
            continue

        if p not in seen:
            clean.append(p)
            seen.add(p)

    return clean


def parse_list_book(book: str, html: str) -> dict[str, dict]:
    """
    解析 jicheng 條列版。

    理想欄位：
      篇次：1
      篇名：上古天真論
      本文：昔在黃帝...

    也容錯處理：
      - 本文跨多行
      - 同篇名分成多段出現
      - 無篇次時以出現順序補上
    """
    lines = extract_lines(html)

    chapters: dict[str, dict] = {}

    current_title = None
    current_num = None
    current_text_parts = []
    in_body = False
    order_counter = 0

    def save_current():
        nonlocal current_title, current_num, current_text_parts, order_counter

        if not current_title:
            return

        body_text = "\n".join([p for p in current_text_parts if p.strip()])
        paragraphs = []

        # 先依來源換行，再依問答標記切段
        for block in body_text.split("\n"):
            block = normalize_text(block)
            if not block:
                continue
            paragraphs.extend(split_by_speaker(block))

        paragraphs = clean_paragraphs(paragraphs)

        if not paragraphs:
            return

        if current_num is None:
            order_counter += 1
            current_num = order_counter

        title = normalize_title(current_title)

        # 同篇名若出現多次，合併本文
        if title in chapters:
            old = chapters[title]
            old_paras = old["paragraphs"]
            seen = set(old_paras)
            for p in paragraphs:
                if p not in seen:
                    old_paras.append(p)
                    seen.add(p)
        else:
            chapters[title] = {
                "book": book,
                "title": title,
                "num": current_num,
                "paragraphs": paragraphs,
                "source_url": URLS[book],
            }

    for line in lines:
        line = normalize_text(line)

        if is_page_noise(line):
            continue

        key, value = strip_field_label(line)

        if key == "篇名":
            save_current()
            current_title = value
            current_num = None
            current_text_parts = []
            in_body = False
            continue

        if current_title is None:
            continue

        if key in ("篇次", "序號", "卷次"):
            current_num = parse_num(value)
            in_body = False
            continue

        if key == "本文":
            in_body = True
            if value:
                current_text_parts.append(value)
            continue

        # 其他欄位一律不收，避免抓到 metadata
        if key is not None:
            in_body = False
            continue

        # 本文跨行續接
        if in_body:
            current_text_parts.append(line)

    save_current()

    # 若篇次全部都缺，用目前順序補
    rows = sorted(chapters.values(), key=lambda x: x["num"] or 9999)
    for i, item in enumerate(rows, 1):
        if item["num"] is None:
            item["num"] = i

    return chapters


def build_catalog() -> dict[tuple[str, str], dict]:
    catalog = {}

    for book, url in URLS.items():
        print(f"[讀取] {book} 條列版：{url}")
        html = get_html(url)
        chapters = parse_list_book(book, html)

        for title, item in chapters.items():
            catalog[(book, title)] = item

        print(f"  ✓ {book} 解析出 {len(chapters)} 篇")

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
        "說明：jicheng.tw 條列版；本檔由程式擷取「本文」欄位，保留來源標點與段落。",
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
        print("  預覽前 5 段：")
        for p in paragraphs[:5]:
            print(f"    - {p[:180]}")
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
            print("可先執行：python scripts/fetch_neijing_jicheng_list.py --list")
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
        description="從 jicheng.tw 條列版抓取《黃帝內經素問》《靈樞》，輸出 Markdown。"
    )
    parser.add_argument("--chapter", help="只抓單篇，如：上古天真論、至真要大論、經脈")
    parser.add_argument("--book", choices=["素問", "靈樞"], help="指定書名")
    parser.add_argument("--highfreq", action="store_true", help="抓第一階段高頻 33 篇")
    parser.add_argument("--all", action="store_true", help="抓指定書全部篇章，需搭配 --book")
    parser.add_argument("--list", action="store_true", help="列出解析出的篇章")
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

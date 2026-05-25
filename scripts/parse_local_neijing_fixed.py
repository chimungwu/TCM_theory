#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
parse_local_neijing_fixed.py

用途：
  讀取 scripts/CM017.txt（素問）與 scripts/CM018.txt（靈樞），
  以 CP950/Big5 解碼，依 1=標題= 切篇，輸出 Markdown。

修正版重點：
  1. 只把「1=標題=」視為新篇名。
  2. 「2=標題=」「3=標題=」只作為段落分隔，不另開檔。
  3. 自動修正 Big5/CP950 亂碼。
  4. 保留原檔標點。
  5. 輸出符合 docs/原文/index.md 體例。

使用方式：
  python scripts/parse_local_neijing_fixed.py --list
  python scripts/parse_local_neijing_fixed.py --highfreq --dry-run
  python scripts/parse_local_neijing_fixed.py --highfreq
  python scripts/parse_local_neijing_fixed.py --chapter 上古天真論 --book 素問 --dry-run
  python scripts/parse_local_neijing_fixed.py --chapter 經脈 --book 靈樞
  python scripts/parse_local_neijing_fixed.py --all

請確認：
  scripts/CM017.txt
  scripts/CM018.txt
"""

import argparse
import re
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

FILES = {
    "素問": BASE_DIR / "CM017.txt",
    "靈樞": BASE_DIR / "CM018.txt",
}

OUT_DIR = PROJECT_ROOT / "docs" / "原文"


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


SPEAKER_MARKERS = [
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
    "黃帝問於岐伯曰：",
    "黃帝問於少師曰：",
    "黃帝問於伯高曰：",
]


def read_text_auto(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"找不到檔案：{path}")

    data = path.read_bytes()

    for enc in ("cp950", "big5", "utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue

    return data.decode("cp950", errors="ignore")


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return text.strip()


def chinese_num_to_int(s: str) -> int | None:
    s = normalize_text(s)
    s = s.replace("第", "").replace("篇", "").replace("章", "").replace("節", "")

    digit = {
        "〇": 0,
        "零": 0,
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
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


def is_main_title_line(line: str) -> bool:
    """
    只認第一層篇名：
      1=標題= 上古天真論篇第一
    """
    return bool(re.match(r"^1\s*=", normalize_text(line)))


def is_subtitle_line(line: str) -> bool:
    """
    章/節小標，不另開檔：
      2=標題=（第一章）
      3=標題=（第一節）
    """
    return bool(re.match(r"^[23]\s*=", normalize_text(line)))


def strip_title_prefix(line: str) -> str:
    """
    去掉：
      1=標題=
      2=標題=
      1=¼ÐÃD=
    """
    line = normalize_text(line)
    line = re.sub(r"^\d+\s*=\s*標題\s*=\s*", "", line)
    line = re.sub(r"^\d+\s*=.*?=\s*", "", line)
    return line.strip(" 　：:。")


def clean_main_title(line: str, book: str) -> tuple[str, int | None] | None:
    title_line = strip_title_prefix(line)

    if not title_line:
        return None

    # 過濾純章節
    if re.fullmatch(r"[（(]第.+?[章節][）)]", title_line):
        return None

    if book == "素問":
        # 例：上古天真論篇第一
        m = re.match(r"^(.+?)篇第?([一二三四五六七八九十百〇零\d]+)$", title_line)
        if m:
            title = normalize_title(m.group(1))
            num = chinese_num_to_int(m.group(2))
            return title, num

    if book == "靈樞":
        # 例：本神第八、經脈第十
        m = re.match(r"^(.+?)第?([一二三四五六七八九十百〇零\d]+)$", title_line)
        if m:
            title = normalize_title(m.group(1))
            num = chinese_num_to_int(m.group(2))
            return title, num

    # 保底
    title = normalize_title(title_line)
    title = re.sub(r"篇第?[一二三四五六七八九十百〇零\d]+$", "", title)
    title = re.sub(r"第[一二三四五六七八九十百〇零\d]+$", "", title)
    title = normalize_title(title)

    if len(title) >= 2:
        return title, None

    return None


def normalize_title(title: str) -> str:
    title = normalize_text(title)
    title = title.replace("　", "")
    title = title.strip(" 　：:。")
    return title


def is_noise_line(line: str) -> bool:
    line = normalize_text(line)

    if not line:
        return True

    noise_keywords = [
        "<>",
        "建檔：",
        "行政院衛生署",
        "中醫藥委員會",
        "何紹唐",
        "校正",
        "底本",
        "檔案",
        "黃帝內經",
    ]

    if any(k in line for k in noise_keywords):
        return True

    if re.fullmatch(r"[\s\-\*_=—─]+", line):
        return True

    return False


def parse_book(book: str, path: Path) -> dict[str, dict]:
    text = read_text_auto(path)
    raw_lines = text.splitlines()

    chapters: dict[str, dict] = {}

    current_title = None
    current_num = None
    buffer: list[str] = []
    order_counter = 0

    def save_current():
        nonlocal current_title, current_num, buffer, order_counter

        if not current_title:
            return

        raw = [normalize_text(x) for x in buffer if normalize_text(x)]
        paragraphs = merge_paragraphs(raw)

        if not paragraphs:
            return

        if current_num is None:
            order_counter += 1
            current_num = order_counter

        chapters[current_title] = {
            "book": book,
            "title": current_title,
            "num": current_num,
            "paragraphs": paragraphs,
            "source_file": str(path),
        }

    for raw_line in raw_lines:
        line = normalize_text(raw_line)

        if is_noise_line(line):
            continue

        if is_main_title_line(line):
            parsed = clean_main_title(line, book)

            if parsed:
                save_current()
                current_title, current_num = parsed
                buffer = []
            continue

        if is_subtitle_line(line):
            # 小章節標題只作為段落斷點
            if current_title:
                buffer.append("")
            continue

        if current_title:
            buffer.append(line)

    save_current()

    return chapters


def split_by_speaker(text: str) -> list[str]:
    """
    依問答標記切段，不額外新增句讀。
    """
    text = normalize_text(text)

    if not text:
        return []

    markers = sorted(SPEAKER_MARKERS, key=len, reverse=True)

    for marker in markers:
        text = text.replace(marker, "\n" + marker)

    parts = []

    for part in text.split("\n"):
        part = normalize_text(part)
        if part:
            parts.append(part)

    return parts


def merge_paragraphs(lines: list[str]) -> list[str]:
    """
    合併正文：
      - 空字串代表章節斷點
      - 非空連續合併
      - 再依「黃帝曰：」「岐伯曰：」等切段
    """
    blocks = []
    buf = ""

    def flush():
        nonlocal buf
        buf = normalize_text(buf)
        if buf:
            blocks.append(buf)
        buf = ""

    for line in lines:
        line = normalize_text(line)

        if not line:
            flush()
            continue

        # 標題殘留不要進正文
        if re.match(r"^\d+\s*=", line):
            flush()
            continue

        buf += line

    flush()

    paragraphs = []

    for block in blocks:
        paragraphs.extend(split_by_speaker(block))

    clean = []
    seen = set()

    for p in paragraphs:
        p = normalize_text(p)

        if not p:
            continue

        if re.match(r"^\d+\s*=", p):
            continue

        if p not in seen:
            clean.append(p)
            seen.add(p)

    return clean


def build_catalog() -> dict[tuple[str, str], dict]:
    catalog = {}

    for book, path in FILES.items():
        print(f"[讀取] {book}：{path}")

        try:
            chapters = parse_book(book, path)
        except Exception as e:
            print(f"[!] 讀取失敗：{book} {path}：{e}", file=sys.stderr)
            continue

        for title, item in chapters.items():
            catalog[(book, title)] = item

        print(f"  ✓ {book} 切出 {len(chapters)} 篇")

    return catalog


def format_markdown(item: dict) -> str:
    book = item["book"]
    title = item["title"]
    num = item["num"]
    paragraphs = item["paragraphs"]
    source_file = item["source_file"]

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
        f"原文來源：{source_file}",
        "說明：本檔由本地 TXT 自動轉碼、依 1=標題= 切篇，2/3=標題= 僅作段落分隔。",
        "-->",
        "",
        "## 篇旨",
        "",
        "> 待補（請補一段簡介本篇大要）",
        "",
        "## 原文",
        "",
    ]

    for p in paragraphs:
        lines.append(f"> {p}")
        lines.append("")

    lines += [
        "## 王冰注",
        "",
        "> 待補。",
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

    target = OUT_DIR / book / f"{title}.md"

    if dry_run:
        print(f"  [dry-run] 將寫入 {target}")
        print(f"  ✓ 段落數：{len(paragraphs)}")
        print("  預覽前 3 段：")
        for p in paragraphs[:3]:
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
        seen_titles = set()
        for book, titles in HIGH_FREQ.items():
            for title in titles:
                key = (book, title)
                if key in seen_titles:
                    continue
                seen_titles.add(key)

                item = catalog.get(key)
                if item:
                    tasks.append(item)
                else:
                    print(f"[!] 高頻篇章找不到：{book}·{title}", file=sys.stderr)

    elif args.all:
        if args.book:
            tasks = [
                item for (book, _), item in catalog.items()
                if book == args.book
            ]
        else:
            tasks = list(catalog.values())

    elif args.chapter:
        matches = []

        for (book, title), item in catalog.items():
            if args.book and book != args.book:
                continue

            if args.chapter == title or args.chapter in title:
                matches.append(item)

        if not matches:
            print(f"[!] 找不到篇章：{args.chapter}")
            print("可先執行：python scripts/parse_local_neijing_fixed.py --list")
            sys.exit(1)

        if len(matches) > 1:
            print("[!] 找到多個相似篇章，請加 --book 或輸入完整篇名：")
            for item in matches:
                print(f"  - {item['book']} {item['num']:02d}. {item['title']}")
            sys.exit(1)

        tasks = matches

    tasks.sort(key=lambda x: (0 if x["book"] == "素問" else 1, x["num"]))
    return tasks


def main():
    parser = argparse.ArgumentParser(
        description="從本地 CM017.txt / CM018.txt 轉碼並切出《素問》《靈樞》Markdown。"
    )
    parser.add_argument("--list", action="store_true", help="列出切出的篇章")
    parser.add_argument("--all", action="store_true", help="輸出全部篇章")
    parser.add_argument("--highfreq", action="store_true", help="只輸出第一階段高頻 33 篇")
    parser.add_argument("--chapter", help="只輸出單篇，如：上古天真論、經脈")
    parser.add_argument("--book", choices=["素問", "靈樞"], help="指定書名")
    parser.add_argument("--dry-run", action="store_true", help="只預覽，不寫檔")
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

    print(f"\n完成。成功 {ok} 篇、失敗 {fail} 篇。")


if __name__ == "__main__":
    main()

"""
fetch_neijing_acupun.py

從 acupun.site「黃帝內經無壓力閱讀版」抓取《素問》《靈樞》篇章原文，
並輸出成 docs/原文/素問 或 docs/原文/靈樞 底下的 Markdown 檔。

使用方式：
  python scripts/fetch_neijing_acupun.py --chapter 至真要大論
  python scripts/fetch_neijing_acupun.py --chapter 本神
  python scripts/fetch_neijing_acupun.py --book 素問 --all
  python scripts/fetch_neijing_acupun.py --highfreq
  python scripts/fetch_neijing_acupun.py --chapter 至真要大論 --dry-run
  python scripts/fetch_neijing_acupun.py --list

需要套件：
  pip install requests beautifulsoup4
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("缺少套件。請先執行：pip install requests beautifulsoup4", file=sys.stderr)
    sys.exit(1)


INDEX_URLS = {
    "素問": "https://acupun.site/huangdineijingsuwen.aspx",
    "靈樞": "https://acupun.site/huangdineijinglingshu.aspx",
}

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

# 你原本想抓的 33 篇高頻引用篇。
# 注意：網站部分篇名使用「藏」而非「臟」、「欬」而非「咳」、「癲狂病」而非「癲狂」。
HIGH_FREQ_CHAPTERS = {
    "素問": [
        "上古天真論", "生氣通天論", "陰陽應象大論", "靈蘭秘典論", "六節藏象論",
        "五藏生成", "五藏別論", "脈要精微論", "經脈別論", "宣明五氣",
        "太陰陽明論", "熱論", "瘧論", "欬論", "舉痛論", "風論", "痺論",
        "痿論", "厥論", "奇病論", "骨空論", "水熱穴論", "調經論",
        "六元正紀大論", "至真要大論",
    ],
    "靈樞": [
        "本神", "經脈", "營衛生會", "癲狂病", "決氣", "海論", "五味", "百病始生",
    ],
}

# 使用者習慣篇名 → 網站篇名。
ALIASES = {
    "五臟生成": "五藏生成",
    "五臟別論": "五藏別論",
    "咳論": "欬論",
    "癲狂": "癲狂病",
}

PIAN_NUM = {
    "素問": {
        "上古天真論": 1, "生氣通天論": 3, "陰陽應象大論": 5, "靈蘭秘典論": 8,
        "六節藏象論": 9, "五藏生成": 10, "五藏別論": 11, "脈要精微論": 17,
        "經脈別論": 21, "宣明五氣": 23, "太陰陽明論": 29, "熱論": 31,
        "瘧論": 35, "欬論": 38, "舉痛論": 39, "風論": 42, "痺論": 43,
        "痿論": 44, "厥論": 45, "奇病論": 47, "骨空論": 60, "水熱穴論": 61,
        "調經論": 62, "六元正紀大論": 71, "至真要大論": 74,
    },
    "靈樞": {
        "本神": 8, "經脈": 10, "營衛生會": 18, "癲狂病": 22, "決氣": 30,
        "海論": 33, "五味": 56, "百病始生": 66,
    },
}


@dataclass(frozen=True)
class ChapterLink:
    book: str
    number: int
    title: str
    url: str


def normalize_title(title: str) -> str:
    title = title.strip()
    title = re.sub(r"^\d+[\.．、]\s*", "", title)
    return ALIASES.get(title, title)


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


def get_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    # acupun 的頁面是 UTF-8；明確指定避免 Windows 環境亂猜編碼。
    r.encoding = "utf-8"
    return r.text


def discover_chapters(book: str) -> dict[str, ChapterLink]:
    """從目錄頁自動找出篇名與 URL。"""
    index_url = INDEX_URLS[book]
    soup = BeautifulSoup(get_html(index_url), "html.parser")
    links: dict[str, ChapterLink] = {}

    for a in soup.find_all("a"):
        text = a.get_text(" ", strip=True)
        href = a.get("href")
        if not text or not href:
            continue

        # 例如：74.至真要大論、08.本神、22.癲狂病
        m = re.match(r"^(\d{1,2})[\.．、]\s*(.+)$", text)
        if not m:
            continue

        number = int(m.group(1))
        title = normalize_title(m.group(2))
        url = urljoin(index_url, href)

        # 只收內經篇章頁，避開其他導覽連結。
        if "huangdineijing/" not in url:
            continue

        links[title] = ChapterLink(book=book, number=number, title=title, url=url)

    return links


def clean_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_noise(text: str) -> bool:
    if not text:
        return True
    if len(text) < 3:
        return True
    noise_keywords = [
        "再探針灸大成", "無壓力閱讀版", "最新消息", "關於我們", "十四經絡",
        "上一篇", "下一篇", "目錄", "大 中 小", "* * *",
    ]
    return any(k in text for k in noise_keywords)


def parse_chapter_page(html: str, title: str) -> list[str]:
    """解析單篇頁面，回傳原文段落。"""
    soup = BeautifulSoup(html, "html.parser")

    # 移除常見非正文元素。
    for sel in ["script", "style", "nav", "footer", "header", "form", "iframe"]:
        for el in soup.select(sel):
            el.decompose()

    raw_lines: list[str] = []

    # acupun 頁面正文在 body 文字中，換行很乾淨；用 get_text('\n') 比只抓 <p> 穩。
    body = soup.body or soup
    text = body.get_text("\n")
    for line in text.splitlines():
        line = clean_text(line)
        if is_noise(line):
            continue
        raw_lines.append(line)

    # 找到標題後，從第一段「黃帝問曰 / 黃帝曰 / 歧伯曰 / 雷公問」等開始收。
    start_patterns = ("黃帝問曰", "黃帝曰", "帝曰", "雷公問", "少師曰", "歧伯曰", "岐伯曰")
    start_idx = None
    for i, line in enumerate(raw_lines):
        if line.startswith(start_patterns):
            start_idx = i
            break

    if start_idx is None:
        # fallback：找含篇名之後的內容。
        for i, line in enumerate(raw_lines):
            if title in line:
                start_idx = i + 1
                break

    if start_idx is None:
        raise ValueError(f"找不到正文起點：{title}")

    paragraphs: list[str] = []
    seen: set[str] = set()
    for line in raw_lines[start_idx:]:
        if is_noise(line):
            continue
        # 避免頁尾導覽或空白字元混入。
        if re.match(r"^\d{1,2}[\.．、]", line):
            continue
        if line in seen:
            continue
        seen.add(line)
        paragraphs.append(line)

    if len(paragraphs) < 3:
        raise ValueError(f"解析後段落太少，可能頁面結構已改變：{title}")

    return paragraphs


def format_markdown(book: str, title: str, number: int, paragraphs: Iterable[str], source_url: str) -> str:
    pian_chinese = num_to_chinese(number)
    display_title = f"{title}篇第{pian_chinese}"

    lines = [
        "---",
        "tags:",
        "  - 原文",
        f"  - {book}",
        f"  - {title}",
        "---",
        "",
        f"# {book}·{display_title}",
        "",
        f"> 來源：{source_url}",
        "",
        "## 篇旨",
        "",
        "> 待補（請補一段簡介本篇大要）",
        "",
        "## 原文",
        "",
    ]

    for para in paragraphs:
        lines.append(f"> {para}")
        lines.append("")

    lines.extend([
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
    ])

    return "\n".join(lines)


def write_chapter(ch: ChapterLink, dry_run: bool = False) -> bool:
    print(f"→ {ch.book}·{ch.title}（篇 {ch.number}）")
    try:
        html = get_html(ch.url)
        paragraphs = parse_chapter_page(html, ch.title)
        md = format_markdown(ch.book, ch.title, ch.number, paragraphs, ch.url)
    except Exception as e:
        print(f"  [!] 失敗：{e}", file=sys.stderr)
        return False

    target = DOCS_BASE / ch.book / f"{ch.title}.md"
    if dry_run:
        print(f"  [dry-run] 抓到 {len(paragraphs)} 段，將寫入 {target}")
        print("  [preview]", paragraphs[0][:80])
        return True

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(md, encoding="utf-8")
    print(f"  ✓ 抓到 {len(paragraphs)} 段，寫入 {target}")
    return True


def resolve_targets(args) -> list[ChapterLink]:
    books = [args.book] if args.book else ["素問", "靈樞"]
    all_links: dict[str, ChapterLink] = {}

    for book in books:
        links = discover_chapters(book)
        for title, link in links.items():
            all_links[f"{book}:{title}"] = link

    if args.list:
        for key in sorted(all_links):
            ch = all_links[key]
            print(f"{ch.book}\t{ch.number:02d}\t{ch.title}\t{ch.url}")
        return []

    if args.chapter:
        title = normalize_title(args.chapter)
        matches = [ch for ch in all_links.values() if ch.title == title]
        if not matches:
            # 支援模糊包含。
            matches = [ch for ch in all_links.values() if title in ch.title or ch.title in title]
        if not matches:
            raise ValueError(f"找不到篇章：{args.chapter}。可先執行 --list 查看可用篇名。")
        return matches

    if args.highfreq:
        targets: list[ChapterLink] = []
        for book, titles in HIGH_FREQ_CHAPTERS.items():
            if args.book and args.book != book:
                continue
            links = discover_chapters(book)
            for t in titles:
                title = normalize_title(t)
                if title not in links:
                    print(f"  [!] 目錄找不到：{book}·{title}", file=sys.stderr)
                    continue
                targets.append(links[title])
        return targets

    if args.all:
        return list(all_links.values())

    raise ValueError("請指定 --chapter、--highfreq、--all 或 --list。")


def main() -> None:
    parser = argparse.ArgumentParser(description="從 acupun.site 抓取《黃帝內經》篇章並輸出 Markdown")
    parser.add_argument("--chapter", help="指定篇名，如：至真要大論、本神、五臟生成")
    parser.add_argument("--book", choices=["素問", "靈樞"], help="限制書名")
    parser.add_argument("--highfreq", action="store_true", help="抓取預設 33 篇高頻引用篇")
    parser.add_argument("--all", action="store_true", help="抓取指定書或兩書全部篇章")
    parser.add_argument("--list", action="store_true", help="列出可抓取篇章")
    parser.add_argument("--dry-run", action="store_true", help="只測試，不寫檔")
    parser.add_argument("--delay", type=float, default=1.0, help="篇章之間延遲秒數，預設 1 秒")
    args = parser.parse_args()

    try:
        targets = resolve_targets(args)
    except Exception as e:
        print(f"[!] {e}", file=sys.stderr)
        sys.exit(1)

    if args.list:
        return

    ok = 0
    fail = 0
    for ch in targets:
        if write_chapter(ch, dry_run=args.dry_run):
            ok += 1
        else:
            fail += 1
        time.sleep(args.delay)

    print(f"\n完成。成功 {ok} 篇、失敗 {fail} 篇。")


if __name__ == "__main__":
    main()

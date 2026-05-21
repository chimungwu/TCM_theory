"""
parse_neijing.py
從 Big5 編碼之 CM017.txt（素問）、CM018.txt（靈樞）正確轉碼，
產生 33 篇高頻引用篇之原文到 docs/原文/。

源檔格式：
  1=標題= 〔篇名篇第N〕     ← 篇之分界
  2=標題=（第N章）          ← 章之分界（編檔者所加，作段落界）
  〔原文，每行約 35 字自動換行〕

源檔提供：行政院衛生署中醫藥委員會建檔。

使用：
  python scripts/parse_neijing.py            # 產生 33 篇
  python scripts/parse_neijing.py --dry-run  # 只顯示，不寫檔
"""

import argparse
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_BASE = SCRIPT_DIR.parent / "docs" / "原文"
CM_SUWEN = SCRIPT_DIR / "CM017.txt"      # 素問
CM_LINGSHU = SCRIPT_DIR / "CM018.txt"    # 靈樞

# 33 篇高頻引用篇 = (篇次, 檔名)
#   檔名用原文異體字（與源檔篇名一致），原文頁求其verbatim
TARGETS_SUWEN = {
    1:  "上古天真論",
    3:  "生氣通天論",
    5:  "陰陽應象大論",
    8:  "靈蘭秘典論",
    9:  "六節藏象論",
    10: "五藏生成",      # 源用「藏」
    11: "五藏別論",      # 源用「藏」
    17: "脈要精微論",
    21: "經脈別論",
    23: "宣明五氣",
    29: "太陰陽明論",
    31: "熱論",
    35: "瘧論",
    38: "欬論",          # 源用「欬」
    39: "舉痛論",
    42: "風論",
    43: "痺論",
    44: "痿論",
    45: "厥論",
    47: "奇病論",
    60: "骨空論",
    61: "水熱穴論",
    62: "調經論",
    71: "六元正紀大論",
    74: "至真要大論",
}
TARGETS_LINGSHU = {
    8:  "本神",
    10: "經脈",
    18: "營衛生會",
    22: "癲狂",
    30: "決氣",
    33: "海論",
    56: "五味",
    66: "百病始生",
}


# ── 造字對照表 ───────────────────────────────────────────────
# 源檔為《內經》生僻古字所造之 Big5 自訂字（0x82xx 等）。
# 以下對照由《內經》固定文本之上下文逐一判定。
# 〔□〕= 上下文仍待校（罕用、僅 1-2 見）。
GAIJI_MAP = {
    "824a": "脅", "8247": "胻", "8252": "䀮", "8250": "䐜", "824e": "䐃",
    "825c": "焫", "82a8": "蠃", "825e": "郄", "8248": "腨", "82a9": "黅",
    "8246": "髃", "8242": "𩩲", "82b8": "骬", "824f": "䏚", "8244": "骶",
    "8258": "㿉", "8256": "瘻", "826b": "㑊", "8257": "㿗", "8272": "瞤",
    "82af": "觀", "8263": "䪼", "85e2": "葉", "8267": "譩", "82b2": "綿",
    "8241": "髎", "82a7": "膂", "82ba": "遍", "82bf": "蓄", "82b9": "水",
    "825d": "炲", "8279": "痓", "8278": "憹", "82d2": "疏", "82b4": "虻",
    "8260": "蛕", "82c6": "秔", "827a": "鬪", "8255": "㾓", "82a2": "髴",
    "86f3": "閉", "8273": "顖", "827b": "皶", "82a1": "瞚", "82a3": "鰂",
    "82ab": "霒", "82ac": "秕", "82ad": "狢", "82ae": "陳", "82aa": "昏",
    "82b1": "礰", "82b3": "蚊", "8269": "㕮", "8249": "肬", "82b6": "椎",
    "82b7": "僻", "8270": "顬", "86f5": "瘛", "82bc": "聹", "86f6": "斲",
    "8275": "癧", "82c1": "呪", "84e9": "船", "82c3": "栝", "82c4": "蔞",
    "82bd": "穀", "82db": "鼕", "82c0": "暶", "8265": "紜", "827d": "䐢",
    "827e": "㶼", "82a5": "䯏", "82a6": "髁", "8266": "腠", "83d7": "膚",
    "8245": "骬", "82be": "診", "824c": "䏖", "825a": "陵", "82c5": "翹",
    # 仍待校（上下文不明確）
    "827c": "〔□〕", "82bb": "〔□〕", "82df": "〔□〕",
}


def decode_neijing(raw):
    """逐位元組解碼：big5hkscs 正常解，造字碼查表替換。"""
    out = []
    i = 0
    n = len(raw)
    while i < n:
        b = raw[i]
        if b < 0x80:
            out.append(chr(b))
            i += 1
            continue
        pair = raw[i:i + 2]
        try:
            out.append(pair.decode("big5hkscs"))
        except Exception:
            hp = pair.hex()
            out.append(GAIJI_MAP.get(hp, "〔?〕"))
        i += 2
    return "".join(out)


def parse_book(path):
    """解析一本書，回傳 [(篇次, 篇名, [段落, ...]), ...]。"""
    raw = path.read_bytes()
    text = decode_neijing(raw)
    lines = text.split("\n")

    chapters = []
    cur = None
    cur_para = []          # 當前章之累積行
    paragraphs = []        # 當前篇之所有段落

    def flush_para():
        nonlocal cur_para
        if cur_para:
            # 行併為一段（去掉換行造成之斷字）
            joined = "".join(s.strip() for s in cur_para)
            if joined:
                paragraphs.append(joined)
            cur_para = []

    def flush_chapter():
        nonlocal cur, paragraphs
        if cur is not None:
            flush_para()
            chapters.append((cur["num"], cur["title"], paragraphs))
        paragraphs = []

    pian_index = 0
    for line in lines:
        if line.startswith("1=標題="):
            flush_chapter()
            pian_index += 1
            title = line.split("=", 2)[2].strip()
            cur = {"num": pian_index, "title": title}
        elif line.startswith("2=標題="):
            # 章界——作段落分隔
            flush_para()
        elif cur is not None:
            if line.strip():
                cur_para.append(line)
            else:
                # 空行亦作段落分隔
                flush_para()
    flush_chapter()
    return chapters


def num_to_chinese(n):
    chars = "零一二三四五六七八九"
    if n < 10:
        return chars[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + chars[n - 10]
    tens, ones = divmod(n, 10)
    return chars[tens] + "十" + (chars[ones] if ones else "")


def format_chapter(book, pian_num, src_title, paragraphs):
    """產生符合本網站體例之 markdown。"""
    pian_cn = num_to_chinese(pian_num)
    # 篇名：去除源檔篇名中之「篇第N」「第N」尾綴，取純篇名
    bare = re.sub(r"篇?第[一二三四五六七八九十]+.*$", "", src_title).strip()
    full_title = f"{bare}篇第{pian_cn}"

    out = [
        "---",
        "tags:",
        "  - 原文",
        f"  - {book}",
        f"  - {bare}",
        "---",
        "",
        f"# {book}·{full_title}",
        "",
        "> 底本：行政院衛生署中醫藥委員會建檔本（春秋戰國·佚名·黃帝內經）",
        "",
        "## 篇旨",
        "",
        "> 待補（請補一段簡介本篇大要）",
        "",
        "## 原文",
        "",
    ]
    for para in paragraphs:
        out.append(f"> {para}")
        out.append("")

    out += [
        "## 王冰注",
        "",
        "> 隨原文段落附之，待補。",
        "",
        "## 註家集釋",
        "",
        "> 馬蒔、張介賓《類經》、張志聰《集註》等之擇要，待補。",
        "",
        "## 主題頁引用",
        "",
        "> 引用本篇之主題頁列表，待自動匯整。",
    ]
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description="從 Big5 源檔轉碼《內經》原文")
    parser.add_argument("--dry-run", action="store_true", help="只顯示，不寫檔")
    args = parser.parse_args()

    if not CM_SUWEN.exists() or not CM_LINGSHU.exists():
        print(f"找不到源檔：{CM_SUWEN} / {CM_LINGSHU}")
        sys.exit(1)

    jobs = [
        ("素問", CM_SUWEN, TARGETS_SUWEN),
        ("靈樞", CM_LINGSHU, TARGETS_LINGSHU),
    ]

    total = 0
    for book, path, targets in jobs:
        chapters = parse_book(path)
        by_num = {num: (title, paras) for num, title, paras in chapters}
        print(f"\n=== {book}（源檔共 {len(chapters)} 篇）===")
        for pian_num, fname in sorted(targets.items()):
            if pian_num not in by_num:
                print(f"  [!] 篇 {pian_num} 不存在於源檔")
                continue
            src_title, paras = by_num[pian_num]
            content = format_chapter(book, pian_num, src_title, paras)
            target = DOCS_BASE / book / f"{fname}.md"
            char_count = sum(len(p) for p in paras)
            if args.dry_run:
                print(f"  [dry-run] {fname}.md ← 篇{pian_num} {src_title}"
                      f"（{len(paras)} 段、{char_count} 字）")
            else:
                target.write_text(content, encoding="utf-8")
                print(f"  ✓ {fname}.md（{len(paras)} 段、{char_count} 字）")
                total += 1

    print(f"\n完成。共寫入 {total} 篇。")


if __name__ == "__main__":
    main()

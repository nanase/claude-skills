#!/usr/bin/env python3
"""harvest.py — harvest.sh から渡される差分を読み、語の置き換え候補を Markdown で出す。

推敲コミットの差分には、書き手が黙って直した語がそのまま残っている。
似た行どうしを対応付け、違っている範囲だけを語の単位まで広げて取り出す。
仕分けは人が行う。ここでは候補を並べるところまでを担う。
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from difflib import SequenceMatcher

# 行の対応付けをこの類似度以上で認める。下げると別の文どうしが繋がる。
LINE_MATCH_RATIO = 0.7

# 語の置き換えとして扱う最大の長さ。超えるものは文の書き換えとみなす。
MAX_SPAN = 14

# この長さ以下の一致は語の内部とみなし、前後の差分と 1 つに繋ぐ。
BRIDGE = 2

# 語尾・体言止めの差を無視して比べるために落とす末尾。
TAIL = re.compile(r"(である|です|ます|する|した|とする|となる|になる)?[。、]?$")

CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")

# 語の内部として左右に広げてよい文字。ひらがなは送り仮名・助詞なので境界にする。
WORDISH = re.compile(r"[\u30a0-\u30ff\u4e00-\u9fffA-Za-z0-9_]")


def is_candidate(old: str, new: str) -> bool:
    old, new = old.strip(), new.strip()
    if not old or not new or old == new:
        return False
    if len(old) > MAX_SPAN or len(new) > MAX_SPAN:
        return False
    if len(old) == 1 and len(new) == 1:
        return False
    if not CJK.search(old) and not CJK.search(new):
        return False
    # 語尾・体言止めの差は文体規則が担うので、語彙の候補から外す。
    if TAIL.sub("", old) == TAIL.sub("", new):
        return False
    # 片方がもう片方を丸ごと含むなら、語の置き換えでなく加筆・削除である。
    if (old in new or new in old) and abs(len(old) - len(new)) >= 3:
        return False
    return True


def merge_opcodes(opcodes):
    """短い一致を挟んだ差分どうしを 1 つに繋ぎ、語のまとまりに戻す。"""
    groups: list[list[int]] = []
    pending: list[int] | None = None
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            if pending is not None and (i2 - i1) > BRIDGE:
                groups.append(pending)
                pending = None
            continue
        if pending is None:
            pending = [i1, i2, j1, j2]
        else:
            pending[1], pending[3] = i2, j2
    if pending is not None:
        groups.append(pending)
    return groups


def widen(old_line: str, new_line: str, i1: int, i2: int, j1: int, j2: int):
    """差分の範囲を、前後の共通する語構成文字まで広げる。"""
    while i1 > 0 and j1 > 0 and old_line[i1 - 1] == new_line[j1 - 1] and WORDISH.match(old_line[i1 - 1]):
        i1 -= 1
        j1 -= 1
    while (
        i2 < len(old_line)
        and j2 < len(new_line)
        and old_line[i2] == new_line[j2]
        and WORDISH.match(old_line[i2])
    ):
        i2 += 1
        j2 += 1
    return old_line[i1:i2], new_line[j1:j2]


def spans(old_line: str, new_line: str):
    matcher = SequenceMatcher(None, old_line, new_line, autojunk=False)
    if matcher.ratio() < LINE_MATCH_RATIO:
        return
    for i1, i2, j1, j2 in merge_opcodes(matcher.get_opcodes()):
        old, new = widen(old_line, new_line, i1, i2, j1, j2)
        if is_candidate(old, new):
            yield old.strip(), new.strip()


def pair_lines(removed: list[str], added: list[str]):
    """同じ hunk 内で、最も似ている行どうしを 1 対 1 で結ぶ。"""
    used: set[int] = set()
    for old_line in removed:
        best, best_ratio = None, LINE_MATCH_RATIO
        for index, new_line in enumerate(added):
            if index in used:
                continue
            ratio = SequenceMatcher(None, old_line, new_line, autojunk=False).ratio()
            if best_ratio < ratio < 1.0:
                best, best_ratio = index, ratio
        if best is not None:
            used.add(best)
            yield old_line, added[best]


def skip_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("```"):
        return True
    if set(stripped) <= set("|- "):
        return True
    return not CJK.search(stripped)


def main() -> None:
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8")

    pairs: Counter[tuple[str, str]] = Counter()
    sources: dict[tuple[str, str], str] = {}

    subject = ""
    in_message = False
    removed: list[str] = []
    added: list[str] = []

    def flush() -> None:
        for old_line, new_line in pair_lines(removed, added):
            for pair in spans(old_line, new_line):
                pairs[pair] += 1
                sources.setdefault(pair, subject)
        removed.clear()
        added.clear()

    for raw in sys.stdin:
        line = raw.rstrip("\n")

        if line.startswith("commit "):
            flush()
            subject = ""
            in_message = True
            continue

        if in_message:
            if line.startswith("    "):
                if not subject:
                    subject = line.strip()
                continue
            if line.startswith(("diff --git", "@@")):
                in_message = False
            else:
                continue

        if line.startswith(("diff --git", "@@", "index ", "new file", "deleted file")):
            flush()
            continue
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("-") and not skip_line(line[1:]):
            removed.append(line[1:])
        elif line.startswith("+") and not skip_line(line[1:]):
            added.append(line[1:])

    flush()

    print("# 語の置き換え候補")
    print()
    print("Markdown の変更履歴から機械的に拾ったものである。誤検出を含む。")
    print("残すものを選び、既存の規則で説明できるかを確かめてから VOCABULARY.md へ移す。")
    print()

    if not pairs:
        print("候補なし。")
        return

    print("| 件数 | 元 | 直した語 | 初出 |")
    print("| --- | --- | --- | --- |")
    for (old, new), count in pairs.most_common():
        origin = sources.get((old, new), "")[:26]
        print(f"| {count} | {old} | {new} | {origin} |")


if __name__ == "__main__":
    main()

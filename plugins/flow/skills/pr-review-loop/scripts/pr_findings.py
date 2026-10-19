#!/usr/bin/env python3
"""pr_findings.py — pr-findings.sh から渡される JSON を集計し、Markdown で出力する。

CodeRabbit のレビュー本文は Outside diff range comments / Nitpick comments を
`<details>` の入れ子で畳んでおり、増分レビューは差分に触れた指摘しか再掲しない。
そのため「最新レビューに出ない = 対応済み」は誤りで、全レビュー本文の和集合を
「一度でも指摘された項目」として扱い、対応記録（PR コメントでのフィンガープリント
言及）の有無で対応済みを判定する。

節の見出しとファイルの示し方には形式の揺れがある。取りこぼすと未対応 0 件と誤って数える。
見つかっている形式は ../CODERABBIT.md にまとめてある。形式を足したら pr_findings_test.py に
検体を足し、python3 pr_findings_test.py で全形式が通ることを確かめる。
"""
import json
import re
import sys
from html import unescape

FINGERPRINT_RE = re.compile(r"<!-- cr-comment:v1:([0-9a-f]+) -->")
# 項目の先頭行は 2 形式ある。「`行`: 観点 | 重大度」の 1 行か、「`パス:行`」だけの行の次に
# 「観点 | 重大度」の行が続く形である。後者のパスは `<summary>` 末尾の `<code>` と違って
# ディレクトリまで含むので、こちらを優先する。本文で関連箇所を `パス:行` だけの行で示すことがあり、
# それを次の項目と取り違えないよう、後者は次の行が「観点 | ...」のときに限る。
# 観点・重大度は、強調が斜体（`_観点_ | _重大度_`）の形と、太字（`**観点** | **重大度**`）の形がある。
# 太字の形では、`<summary>` の強調も `<em>` から `<strong>` に変わる。
EMPHASIS = r"(?:_|\*\*)"
ITEM_RE = re.compile(
    r"^`(?:(\d+(?:-\d+)?)`:[ \t]*(.*)"
    rf"|(\S+?):(\d+(?:-\d+)?)`[ \t]*\n({EMPHASIS}[^\n]*{EMPHASIS}[ \t]*\|[^\n]*))$",
    re.MULTILINE,
)
# 見出しは行頭の太字で書かれる。1 行を占めることもあれば、同じ行に本文が続くこともある。
TITLE_RE = re.compile(r"^\*\*(.+?)\*\*", re.MULTILINE)
SEVERITY_RE = re.compile(rf"{EMPHASIS}([🔴🟠🟡🟢🔵][^_*]*){EMPHASIS}")

# 節の中の対象ファイルも 2 形式ある。畳み形式はファイルごとに `<summary>パス (N)</summary>` で
# まとめるが、太字形式にまとめ役は無く、項目ごとの `<summary>` 末尾に `<code>パス:行</code>` が
# 入る（ファイル名だけのこともあり、そのときは ITEM_RE の先頭行が持つパスを使う）。
# その `<summary>` には重大度や見出しも並び、見出し自体が `<code>` を含むことがあるため、
# 末尾に接した最後の `<code>` だけをパスとして拾う。
# 件数は `(N)` の形と `: N` の形がある。
COUNT = r"(?: \(\d+\)|: \d+)"
FILE_RE = re.compile(rf"^<summary>([^<]+?){COUNT}</summary>", re.MULTILINE)
FILE_CODE_RE = re.compile(r"^<summary>.*<code>([^<>]+?):\d+(?:-\d+)?</code></summary>", re.MULTILINE)

# 節の見出しには 2 形式ある。CodeRabbit は畳み（`<details>`）で出すこともあれば、
# 引用ブロックの中の太字で出すこともある。
# 引用の `> ` は strip_blockquote が先に落とすので、ここでは考えなくてよい。
SECTION_LABELS = {
    "outside_diff": "⚠️ Outside diff range comments",
    "nitpick": "🧹 Nitpick comments",
}


def heading_pattern(label: str) -> str:
    """節見出しの 2 形式（畳みの summary・太字）どちらにも当たる断片を返す。"""
    escaped = re.escape(label)
    return rf"(?:<summary>{escaped}|\*\*{escaped})"


SECTION_MARKERS = {
    kind: re.compile(heading_pattern(label) + COUNT) for kind, label in SECTION_LABELS.items()
}
# 節の終わりは、次の節の見出しか、レビュー本文の他の畳みの始まりで判定する。
STOP_MARKERS = [re.compile(heading_pattern(label)) for label in SECTION_LABELS.values()] + [
    re.compile(p)
    for p in (
        r"<summary>🤖 Prompt for all review comments with AI agents",
        r"<summary>🤖 Prompt to fix review comments",
        r"<summary>🪄 Autofix",
        r"<summary>ℹ️ Review info",
        r"<summary>📥 Commits",
        r"<summary>📒 Files selected",
        r"<summary>🚧 Files skipped",
    )
]


def strip_blockquote(text: str) -> str:
    return "\n".join(re.sub(r"^> ?", "", line) for line in text.split("\n"))


def section_span(text: str, marker: "re.Pattern[str]") -> "tuple[int, int] | None":
    m = marker.search(text)
    if not m:
        return None
    start = m.end()
    end = len(text)
    for stop in STOP_MARKERS:
        sm = stop.search(text, start)
        if sm and sm.start() < end:
            end = sm.start()
    return start, end


def parse_items(section_text: str) -> list[dict]:
    events = []
    for file_re in (FILE_RE, FILE_CODE_RE):
        for m in file_re.finditer(section_text):
            events.append((m.start(), "file", m.group(1).strip()))
    for m in ITEM_RE.finditer(section_text):
        events.append((m.start(), "item", m))
    events.sort(key=lambda e: e[0])

    items = []
    current_file = None
    pending = None  # (current_file, ITEM_RE の Match, 項目の開始位置)
    for pos, kind, val in events:
        if kind == "file":
            current_file = val
            continue
        # kind == "item"
        if pending is not None:
            items.append(_finish_item(pending, section_text[pending[2] : pos]))
        pending = (current_file, val, pos)
    if pending is not None:
        items.append(_finish_item(pending, section_text[pending[2] :]))
    return items


def _finish_item(pending, body_after_marker: str) -> dict:
    file_path, m, _ = pending
    if m.group(1):
        line_range, tags = m.group(1), m.group(2)
    else:
        file_path, line_range, tags = m.group(3), m.group(4), m.group(5)
    fp = FINGERPRINT_RE.search(body_after_marker)
    # 見出しは ITEM_RE が読んだ行より後ろから探す。太字形式の観点の行も行頭の太字で始まるため、
    # 先頭から探すと観点を見出しと取り違える。
    after = body_after_marker[m.end() - m.start() :]
    title_m = TITLE_RE.search(after)
    sev_m = SEVERITY_RE.search(tags)
    title = title_m.group(1).strip() if title_m else (after.strip().splitlines() or [""])[0][:80]
    return {
        "path": file_path or "(unknown)",
        "line": line_range,
        "severity": sev_m.group(1) if sev_m else "",
        "title": unescape(title),
        "fingerprint": fp.group(1) if fp else None,
    }


def collect_body_findings(reviews: list[dict]) -> dict:
    """全レビュー本文からフィンガープリント単位の和集合を作る。"""
    found = {"outside_diff": {}, "nitpick": {}}
    for rv in reviews:
        if (rv.get("user") or {}).get("login") != "coderabbitai[bot]":
            continue
        body = rv.get("body") or ""
        if not body:
            continue
        text = strip_blockquote(body)
        for kind, marker in SECTION_MARKERS.items():
            span = section_span(text, marker)
            if not span:
                continue
            for item in parse_items(text[span[0] : span[1]]):
                key = item["fingerprint"] or f"{item['path']}:{item['line']}:{item['title']}"
                found[kind].setdefault(key, item)
    return found


def first_line(body: str, limit: int = 80) -> str:
    lines = (body or "").strip().splitlines()
    return lines[0][:limit] if lines else ""


def build_evidence_corpus(issue_comments: list[dict], inline_comments: list[dict]) -> str:
    parts = []
    for c in issue_comments:
        if (c.get("user") or {}).get("login") == "coderabbitai[bot]":
            continue
        parts.append(c.get("body") or "")
    for c in inline_comments:
        if (c.get("user") or {}).get("login") == "coderabbitai[bot]":
            continue
        parts.append(c.get("body") or "")
    return "\n".join(parts)


def main() -> None:
    # Windows では標準入出力がパイプへ繋がれるとロケールのコードページ（日本語環境なら
    # cp932）で開かれ、cp932 に無い文字（— や絵文字）を読み書きすると落ちる。
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    data = json.load(sys.stdin)
    reviews = data.get("reviews", [])
    inline_comments = data.get("inline_comments", [])
    issue_comments = data.get("issue_comments", [])
    resolved_map = data.get("resolved_map", {})

    body_findings = collect_body_findings(reviews)
    evidence = build_evidence_corpus(issue_comments, inline_comments)

    inline_roots = [c for c in inline_comments if not c.get("in_reply_to_id")]
    inline_unresolved = [c for c in inline_roots if not resolved_map.get(str(c["id"]), False)]

    def is_acked(item: dict) -> bool:
        fp = item.get("fingerprint")
        return bool(fp) and fp in evidence

    outside_diff_unresolved = [v for v in body_findings["outside_diff"].values() if not is_acked(v)]
    nitpick_unresolved = [v for v in body_findings["nitpick"].values() if not is_acked(v)]

    out = []
    total_unresolved = len(inline_unresolved) + len(outside_diff_unresolved) + len(nitpick_unresolved)
    out.append("# レビュー指摘一覧\n")
    out.append(f"## 未対応 ({total_unresolved} 件)\n")
    if total_unresolved == 0:
        out.append("なし\n")
    for c in inline_unresolved:
        path = c.get("path", "?")
        line = c.get("line") or c.get("original_line") or "?"
        summary = first_line(c.get("body"))
        out.append(f"- [inline] {path}:{line} (id:{c['id']}) — {summary}")
    for v in outside_diff_unresolved:
        out.append(f"- [outside-diff] {v['path']}:L{v['line']} ({v['severity']}) — {v['title']}")
    for v in nitpick_unresolved:
        sev = f" ({v['severity']})" if v["severity"] else ""
        out.append(f"- [nitpick]{sev} {v['path']}:L{v['line']} — {v['title']}")

    out.append(f"\n## インラインコメント (全 {len(inline_roots)} 件)\n")
    for c in inline_roots:
        resolved = resolved_map.get(str(c["id"]), False)
        mark = "✅ 解決済み" if resolved else "❌ 未解決"
        path = c.get("path", "?")
        line = c.get("line") or c.get("original_line") or "?"
        summary = first_line(c.get("body"))
        out.append(f"- {mark} {path}:{line} (id:{c['id']}) — {summary}")

    for kind, label in (("outside_diff", "Outside diff range comments"), ("nitpick", "Nitpick comments")):
        values = list(body_findings[kind].values())
        out.append(f"\n## {label} (全 {len(values)} 件)\n")
        for v in values:
            mark = "✅ 対応記録あり" if is_acked(v) else "❌ 未対応"
            fp = f" fingerprint:{v['fingerprint']}" if v["fingerprint"] else ""
            sev = f" ({v['severity']})" if v["severity"] else ""
            out.append(f"- {mark} {v['path']}:L{v['line']}{sev}{fp} — {v['title']}")

    print("\n".join(out))


if __name__ == "__main__":
    main()

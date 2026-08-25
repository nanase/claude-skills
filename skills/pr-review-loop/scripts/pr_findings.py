#!/usr/bin/env python3
"""pr_findings.py — pr-findings.sh から渡される JSON を集計し、Markdown で出力する。

CodeRabbit のレビュー本文は Outside diff range comments / Nitpick comments を
`<details>` の入れ子で畳んでおり、増分レビューは差分に触れた指摘しか再掲しない。
そのため「最新レビューに出ない = 対応済み」は誤りで、全レビュー本文の和集合を
「一度でも指摘された項目」として扱い、対応記録（PR コメントでのフィンガープリント
言及）の有無で対応済みを判定する。
"""
import json
import re
import sys
from html import unescape

FINGERPRINT_RE = re.compile(r"<!-- cr-comment:v1:([0-9a-f]+) -->")
ITEM_RE = re.compile(r"^`(\d+(?:-\d+)?)`:\s*(.*)$", re.MULTILINE)
FILE_RE = re.compile(r"^<summary>([^<]+?) \(\d+\)</summary>", re.MULTILINE)
TITLE_RE = re.compile(r"^\*\*(.+?)\*\*\s*$", re.MULTILINE)
SEVERITY_RE = re.compile(r"_([🔴🟠🟡🟢🔵][^_]*)_")

SECTION_MARKERS = {
    "outside_diff": re.compile(r"<summary>⚠️ Outside diff range comments \(\d+\)</summary>"),
    "nitpick": re.compile(r"<summary>🧹 Nitpick comments \(\d+\)</summary>"),
}
STOP_MARKERS = [
    re.compile(p)
    for p in (
        r"<summary>⚠️ Outside diff range comments",
        r"<summary>🧹 Nitpick comments",
        r"<summary>🤖 Prompt for all review comments with AI agents",
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
    for m in FILE_RE.finditer(section_text):
        events.append((m.start(), "file", m.group(1).strip()))
    for m in ITEM_RE.finditer(section_text):
        events.append((m.start(), "item", m))
    events.sort(key=lambda e: e[0])

    items = []
    current_file = None
    pending = None  # (line_range, tags, start_of_body)
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
    line_range, tags = m.group(1), m.group(2)
    fp = FINGERPRINT_RE.search(body_after_marker)
    title_m = TITLE_RE.search(body_after_marker)
    sev_m = SEVERITY_RE.search(tags)
    title = title_m.group(1).strip() if title_m else body_after_marker.strip().splitlines()[0][:80]
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

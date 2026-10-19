#!/usr/bin/env python3
"""rate_limit_status.py — rate-limit-status.sh から渡される PR コメントの JSON を読み、
CodeRabbit のレート制限（Review limit reached）の状態と解除時刻を判定する。

制限中かどうかは文章で判定せず、CodeRabbit が制限メッセージに埋め込む HTML コメントの印
（`<!-- This is an auto-generated comment: rate limited by coderabbit.ai -->`）で判定する。
文章の言い回しは CodeRabbit の都合で何度も変わってきたが、印は変わっていない。
制限が解けてレビューが走ると、サマリが書き換わって印も消える。
印が見つからず「Review limit reached」の見出しだけがあるときは、印の付け方が変わった疑いがある。
制限を見落として待ち続けるより安全なので、見出しで制限中と扱い、DETECTED_BY=heading で知らせる。

解除までの分数は文章からしか取れないため、読めたときだけ使う補助にする。読めないときは
止まらず、既定の待ち時間（DEFAULT_MINUTES）で解除時刻を出し、BASIS=default で知らせる。
分数の書き方の揺れは testdata/rate_limit/ に実物を置き、rate_limit_status_test.py で確かめる。
文言が増えたらそこへ実物を足す。

解除時刻はコメントの updated_at を起点に計算する。制限に当たるたびに同じコメントが
上書きされるので、何度待ち直しても最新のメッセージから計算し直せる。
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone

BOT_LOGIN = "coderabbitai[bot]"

# 制限メッセージの始まりと終わりに置かれる印。終わりの印は "end of auto-generated comment: ..." である。
LIMIT_START_RE = re.compile(r"<!--\s*This is an auto-generated comment: rate limited by coderabbit\.ai\s*-->", re.I)
LIMIT_END_RE = re.compile(r"<!--\s*end of auto-generated comment: rate limited by coderabbit\.ai\s*-->", re.I)
# 印が無いときの予備。制限メッセージの見出しで、これまでの文言の変化でも変わっていない。
LIMIT_HEADING_RE = re.compile(r"^[>\s]*#+\s*Review limit reached", re.I | re.M)

# 表示される分数は切り捨てで秒の情報が無く、計算した解除時刻は実際より最大 1 分弱早くなりうる。
# 早すぎる促しは「数秒待て」と返されるうえ、順番待ちの PR があると待ち直しになるので、余分に待つ。
BUFFER_MINUTES = 3

# 分数が読めないときの待ち時間。CodeRabbit の枠は 1 時間あたりの回数で決まるため、
# 1 時間待てば少なくとも 1 枠は空く見込みである。
DEFAULT_MINUTES = 60

# 「41 minutes」「1 hour 5 minutes」「30 seconds」のような長さの表記。単位は秒に直して足す。
DURATION_RE = re.compile(r"(\d+)\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b", re.I)
UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1}


def author(c: dict) -> "str | None":
    # 退会したアカウントのコメントは user が null で返る。
    return (c.get("user") or {}).get("login")


def detected_by(body: str) -> "str | None":
    """制限メッセージを何で見つけたかを返す。制限メッセージが無ければ None を返す。"""
    if LIMIT_START_RE.search(body):
        return "marker"
    if LIMIT_HEADING_RE.search(body):
        return "heading"
    return None


def latest_limited_comment(comments: list[dict]) -> "dict | None":
    """CodeRabbit のコメントのうち、制限メッセージを持つ最新（updated_at 最大）のものを返す。

    投稿者を CodeRabbit に絞る。人が制限メッセージを引用したコメントを拾うと、無関係な時刻を起点にしてしまう。
    """
    limited = [c for c in comments if author(c) == BOT_LOGIN and detected_by(c.get("body") or "")]
    return max(limited, key=lambda c: c["updated_at"], default=None)


def limit_message(body: str) -> str:
    """制限メッセージの本文のうち、畳み（`<details>`）より前の部分を返す。

    畳みの中には「過去 7 日」「1 時間あたり 4 回」のような、待ち時間でない数字が並ぶ。
    """
    start = LIMIT_START_RE.search(body) or LIMIT_HEADING_RE.search(body)
    end = LIMIT_END_RE.search(body, start.end())
    block = body[start.end() : end.start() if end else len(body)]
    return re.split(r"<details\b", block, maxsplit=1, flags=re.I)[0]


def displayed_minutes(body: str) -> "int | None":
    """制限メッセージに出ている解除までの分数を返す。読めないときは None を返す。

    文言は CodeRabbit の都合で変わるので、文の形には頼らず、本文に出る長さの表記だけを拾う。
    時間・分・秒がそれぞれ 1 つまでなら足し合わせ、それより多ければどれが待ち時間か決められないので読めない扱いにする。
    秒を含むときは分へ切り上げる。
    """
    found = {unit: [] for unit in UNIT_SECONDS}
    for number, unit in DURATION_RE.findall(limit_message(body)):
        found[unit[0].lower()].append(int(number))
    if not any(found.values()) or any(len(v) > 1 for v in found.values()):
        return None
    seconds = sum(UNIT_SECONDS[unit] * sum(v) for unit, v in found.items())
    return -(-seconds // 60)


def parse_timestamp(ts: str) -> datetime:
    # GitHub の timestamp は UTC の ISO8601（例 2026-08-25T16:35:06Z）で返る。
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def format_timestamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def judge(comments: list[dict], now: datetime) -> list[str]:
    """判定結果を key=value の行で返す。"""
    comment = latest_limited_comment(comments)
    if comment is None:
        return ["STATUS=no_limit"]

    minutes = displayed_minutes(comment["body"])
    wait_minutes = DEFAULT_MINUTES if minutes is None else minutes + BUFFER_MINUTES
    updated_at = comment["updated_at"]
    deadline = parse_timestamp(updated_at) + timedelta(minutes=wait_minutes)
    remaining = int((deadline - now).total_seconds())

    basis_lines = [
        f"DETECTED_BY={detected_by(comment['body'])}",
        f"BASIS={'default' if minutes is None else 'displayed'}",
        f"MINUTES={'unknown' if minutes is None else minutes}",
        f"UPDATED_AT={updated_at}",
    ]
    if remaining <= 0:
        return ["STATUS=ready", *basis_lines]
    return ["STATUS=waiting", f"REMAINING_SECONDS={remaining}", f"DEADLINE={format_timestamp(deadline)}", *basis_lines]


def main() -> None:
    # Windows では標準入出力がパイプへ繋がれるとロケールのコードページ（日本語環境なら
    # cp932）で開かれ、cp932 に無い文字（— や絵文字）を読み書きすると落ちる。
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # `gh api --paginate --slurp` はページごとの配列を並べた配列を返す。
    comments = [c for page in json.load(sys.stdin) for c in page]
    print("\n".join(judge(comments, datetime.now(timezone.utc))))


if __name__ == "__main__":
    main()

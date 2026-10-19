#!/usr/bin/env python3
"""rate_limit_status_test.py — rate_limit_status.py が制限の印と分数の揺れを正しく扱うことを確かめる。

`python3 rate_limit_status_test.py` で走る。標準ライブラリだけを使い、CI には載せていない。
rate_limit_status.py を触るときに手元で走らせること。

検体は testdata/rate_limit/ に置いたコメント本文である。制限メッセージは前後の印の間だけを
持つ。実物から判定に効く骨格だけを残して合成してある。文言が増えたらここへ足す。
"""
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rate_limit_status import BOT_LOGIN, displayed_minutes, judge

TESTDATA = Path(__file__).parent / "testdata" / "rate_limit"
UPDATED_AT = "2026-10-08T08:14:39Z"


def body(name: str) -> str:
    return (TESTDATA / name).read_text(encoding="utf-8")


def comment(text: str, login: str = BOT_LOGIN, updated_at: str = UPDATED_AT) -> dict:
    return {"user": {"login": login}, "body": text, "updated_at": updated_at}


def at(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# 古い文言。「**Next review available in:** **41 minutes**」。
NEXT_REVIEW = body("next_review_available_in.md")
# 次の文言。「**Next included review available in 8 minutes.**」。
NEXT_INCLUDED = body("next_included_review.md")
# 今の文言。「**Or wait 11 minutes for your next included review.**」。
# 従量課金の「Run on-demand review」のチェックボックスが同じメッセージに並ぶ。
OR_WAIT = body("or_wait.md")
# 制限が解けてレビューが済んだ後のサマリ。制限の印は消えている。
REVIEWED = body("reviewed_summary.md")
# `@coderabbitai review` への返信。
REPLY = body("review_command_reply.md")
# 分数が読めない文言。今の文言の分数だけを言い換えたもの。
UNREADABLE = OR_WAIT.replace("Or wait 11 minutes", "Or wait a little while")


class DisplayedMinutesTest(unittest.TestCase):
    def test_これまでの文言から分数を読める(self) -> None:
        self.assertEqual(displayed_minutes(NEXT_REVIEW), 41)
        self.assertEqual(displayed_minutes(NEXT_INCLUDED), 8)
        self.assertEqual(displayed_minutes(OR_WAIT), 11)

    def test_時間と分の表記を足し合わせる(self) -> None:
        self.assertEqual(displayed_minutes(OR_WAIT.replace("11 minutes", "1 hour 5 minutes")), 65)
        self.assertEqual(displayed_minutes(OR_WAIT.replace("11 minutes", "2 hours")), 120)

    def test_略記と秒も読み秒は分へ切り上げる(self) -> None:
        self.assertEqual(displayed_minutes(OR_WAIT.replace("11 minutes", "5 min")), 5)
        self.assertEqual(displayed_minutes(OR_WAIT.replace("11 minutes", "30 seconds")), 1)
        self.assertEqual(displayed_minutes(OR_WAIT.replace("11 minutes", "1 minute 30 seconds")), 2)

    def test_読めない文言はNoneを返す(self) -> None:
        self.assertIsNone(displayed_minutes(UNREADABLE))

    def test_長さの表記が複数あればどれか決めずにNoneを返す(self) -> None:
        self.assertIsNone(displayed_minutes(OR_WAIT.replace("11 minutes", "11 minutes (or 15 minutes)")))


class JudgeTest(unittest.TestCase):
    def test_制限でないコメントだけならno_limit(self) -> None:
        self.assertEqual(judge([comment(REVIEWED), comment(REPLY)], at(UPDATED_AT)), ["STATUS=no_limit"])

    def test_分数が読めれば表示の分数にバッファを足して待つ(self) -> None:
        # 11 分 + バッファ 3 分 = 14 分後が解除時刻。
        self.assertEqual(
            judge([comment(OR_WAIT)], at("2026-10-08T08:20:39Z")),
            [
                "STATUS=waiting",
                "REMAINING_SECONDS=480",
                "DEADLINE=2026-10-08T08:28:39Z",
                "DETECTED_BY=marker",
                "BASIS=displayed",
                "MINUTES=11",
                f"UPDATED_AT={UPDATED_AT}",
            ],
        )

    def test_解除時刻を過ぎればready(self) -> None:
        self.assertEqual(
            judge([comment(OR_WAIT)], at("2026-10-08T08:28:39Z")),
            ["STATUS=ready", "DETECTED_BY=marker", "BASIS=displayed", "MINUTES=11", f"UPDATED_AT={UPDATED_AT}"],
        )

    def test_分数が読めなければ止まらず既定の60分で待つ(self) -> None:
        self.assertEqual(
            judge([comment(UNREADABLE)], at(UPDATED_AT)),
            [
                "STATUS=waiting",
                "REMAINING_SECONDS=3600",
                "DEADLINE=2026-10-08T09:14:39Z",
                "DETECTED_BY=marker",
                "BASIS=default",
                "MINUTES=unknown",
                f"UPDATED_AT={UPDATED_AT}",
            ],
        )

    def test_制限のコメントが複数あれば最新を起点にする(self) -> None:
        older = comment(NEXT_INCLUDED, updated_at="2026-10-08T07:34:12Z")
        lines = judge([comment(OR_WAIT), older], at(UPDATED_AT))
        self.assertIn(f"UPDATED_AT={UPDATED_AT}", lines)
        self.assertIn("MINUTES=11", lines)

    def test_CodeRabbit以外のコメントは読まない(self) -> None:
        self.assertEqual(judge([comment(OR_WAIT, login="someone")], at(UPDATED_AT)), ["STATUS=no_limit"])


class UnmarkedLimitTest(unittest.TestCase):
    def test_印が無く見出しだけあれば見出しで制限中と扱う(self) -> None:
        unmarked = NEXT_INCLUDED.replace("rate limited by coderabbit.ai", "something else")
        lines = judge([comment(unmarked)], at("2026-10-08T08:15:39Z"))
        self.assertEqual(lines[0], "STATUS=waiting")
        self.assertIn("DETECTED_BY=heading", lines)
        self.assertIn("MINUTES=8", lines)

    def test_印も見出しも無ければno_limit(self) -> None:
        self.assertEqual(judge([comment(REVIEWED)], at(UPDATED_AT)), ["STATUS=no_limit"])


class MalformedCommentTest(unittest.TestCase):
    def test_userやbodyがnullのコメントで落ちない(self) -> None:
        broken = [{"user": None, "body": "x", "updated_at": UPDATED_AT}, {**comment(""), "body": None}]
        self.assertEqual(judge(broken, at(UPDATED_AT)), ["STATUS=no_limit"])


if __name__ == "__main__":
    unittest.main()

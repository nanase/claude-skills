#!/usr/bin/env python3
"""pr_findings_test.py — pr_findings.py がレビュー本文の形式の揺れを取りこぼさないことを確かめる。

`python3 pr_findings_test.py` で走る。標準ライブラリだけを使い、CI には載せていない。
pr_findings.py を触るときに手元で走らせること。

検体は実際のレビュー本文の形式から、判定に効く骨格だけを残して合成してある。testdata/pr_findings/ の
ファイルも同じで、印・見出し・強調・入れ子・件数の書き方を実物どおりに持つ。
形式が増えたらここに検体を足す。
"""
import unittest
from pathlib import Path

from pr_findings import SECTION_MARKERS, collect_body_findings, section_span, strip_blockquote

# 畳み形式。節も対象ファイルも `<details>` でまとめる。
DETAILS_FORM = """**Actionable comments posted: 0**

<details>
<summary>⚠️ Outside diff range comments (2)</summary><blockquote>

<details>
<summary>src/web/pages/users/model.test.ts (1)</summary><blockquote>

`154-168`: _🎯 Functional Correctness_ | _🟡 Minor_ | _⚡ Quick win_

**通知閾値の境界値を追加してください。**

現在のテストは `18` と `84` のみを検証しています。

<!-- cr-comment:v1:aaaaaaaaaaaaaaaaaaaaaaaa -->

</blockquote></details>
<details>
<summary>src/server/service/user.go (1)</summary><blockquote>

`89-100`: _🔐 Security_ | _🟠 Major_ | _⚡ Quick win_

**閲覧範囲を確認してください。**

<!-- cr-comment:v1:bbbbbbbbbbbbbbbbbbbbbbbb -->

</blockquote></details>

</blockquote></details>

<details>
<summary>🧹 Nitpick comments (1)</summary><blockquote>

<details>
<summary>src/server/service/user.go (1)</summary><blockquote>

`12-14`: _📐 Maintainability & Code Quality_ | _🔵 Trivial_

**import を並べ替えてください。**

<!-- cr-comment:v1:cccccccccccccccccccccccc -->

</blockquote></details>

</blockquote></details>

<details>
<summary>ℹ️ Review info</summary>

<details>
<summary>📥 Commits</summary>

Reviewing files that changed from the base of the PR.

</details>

</details>
"""

# 太字形式。節の全体が引用ブロックに入り、節の見出しは太字で、対象ファイルは項目ごとの
# `<summary>` 末尾の `<code>` に入る。見出しが `<code>` を含む検体（2 件目）も混ぜてある。
# 項目の見出しは 1 件目が同じ行に本文を続け、2 件目が 1 行を占める形で、どちらの書かれ方も含めてある。
BLOCKQUOTE_FORM = """
> [!CAUTION]
> Some comments are outside the diff and can't be posted inline due to GitHub limitations.
>
> **⚠️ Outside diff range comments (2)**
>
> <details>
> <summary><em>🟠 Major</em> · <em>🗄️ Data Integrity &amp; Integration</em> · <code>scripts/record-results.ts:198-230</code></summary><blockquote>
>
> `198-230`: _🗄️ Data Integrity & Integration_ | _🟠 Major_ | _⚡ Quick win_
>
> **担当列を条件付きで保護してから書き込む。** `readPlaces` が担当列を読み取った後、排他制御はありません。
>
> <details>
> <summary>🤖 Prompt for AI Agents</summary>
>
> ```
> In `@scripts/record-results.ts` around lines 198 - 230, ...
> ```
>
> </details>
>
> <!-- cr-comment:v1:dcd0c0c176d47a161c8614d9 -->
>
> </blockquote></details>
> <details>
> <summary><em>🟡 Minor</em> · <code>forbidden</code> 中は <code>load()</code> を停止してください。 · <code>src/web/pages/orders/OrderSection.tsx:167-174</code></summary><blockquote>
>
> `167-174`: _🎯 Functional Correctness_ | _🟡 Minor_ | _⚡ Quick win_
>
> **`forbidden` 中は `load()` を停止してください。**
>
> `load()` の先頭で `forbidden` を確認してください。
>
> <!-- cr-comment:v1:0b6ebd1b6447b308bb1209b7 -->
>
> </blockquote></details>

<details>
<summary>🤖 Prompt for all review comments with AI agents</summary>

```
Outside diff comments:
In `@scripts/record-results.ts`:
- Around line 198-230: ...
```

</details>

---

<details>
<summary>ℹ️ Review info</summary>

<details>
<summary>📥 Commits</summary>

Reviewing files that changed from the base of the PR.

</details>

</details>
"""

# 太字形式のうち、項目の先頭行が行範囲だけでなく `パス:行` になる形。
# `<summary>` 末尾の `<code>` はファイル名だけでディレクトリを含まず、観点・重大度の行は先頭行の
# 次の行に分かれる。
PATH_LINE_FORM = """
> [!CAUTION]
> Some comments are outside the diff and can't be posted inline due to GitHub limitations.
>
> **⚠️ Outside diff range comments (1)**
>
> <details>
> <summary><em>🟡 Minor</em> · worktree の分岐を <code>branch-setup</code> に委譲してください。 · <code>SKILL.md:28-31</code></summary><blockquote>
>
> `docs/flow/SKILL.md:28-31`
> _🎯 Functional Correctness_ | _🟡 Minor_ | _⚡ Quick win_
>
> **worktree の分岐を `branch-setup` に委譲してください。**
>
> 両方の手順を満たす順序がありません。
>
> <!-- cr-comment:v1:318a31cf5cd8404e051971f5 -->
>
> </blockquote></details>

---

<details>
<summary>🤖 Prompt to fix review comments</summary>

```
Outside diff comments:
Review comments at @docs/flow/SKILL.md:
- Around line 28-31: ...
```

</details>

---

<details>
<summary>ℹ️ Review info</summary>

</details>
"""


TESTDATA = Path(__file__).parent / "testdata" / "pr_findings"


def body(name: str) -> str:
    return (TESTDATA / name).read_text(encoding="utf-8")


def findings(*bodies: str) -> dict:
    reviews = [{"user": {"login": "coderabbitai[bot]"}, "body": b} for b in bodies]
    return collect_body_findings(reviews)


class DetailsFormTest(unittest.TestCase):
    """畳み形式。従来から読めていた形式を壊していないことを確かめる。"""

    def setUp(self) -> None:
        self.found = findings(DETAILS_FORM)

    def test_outside_diff_2件を拾う(self) -> None:
        items = list(self.found["outside_diff"].values())
        self.assertEqual(len(items), 2)
        self.assertEqual(
            [(i["path"], i["line"]) for i in items],
            [
                ("src/web/pages/users/model.test.ts", "154-168"),
                ("src/server/service/user.go", "89-100"),
            ],
        )
        self.assertEqual(items[0]["title"], "通知閾値の境界値を追加してください。")
        self.assertEqual(items[0]["severity"], "🟡 Minor")
        self.assertEqual(items[0]["fingerprint"], "aaaaaaaaaaaaaaaaaaaaaaaa")

    def test_nitpickを別の節として拾う(self) -> None:
        items = list(self.found["nitpick"].values())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["fingerprint"], "cccccccccccccccccccccccc")

    def test_節の終わりで打ち切る(self) -> None:
        """Review info 以降の畳みを指摘として読み込まない。"""
        fingerprints = {i["fingerprint"] for i in self.found["outside_diff"].values()}
        self.assertNotIn("cccccccccccccccccccccccc", fingerprints)


class BlockquoteFormTest(unittest.TestCase):
    """太字形式。畳み形式しか読めないと、この形式の指摘を丸ごと取りこぼす。"""

    def setUp(self) -> None:
        self.found = findings(BLOCKQUOTE_FORM)

    def test_outside_diff_2件を拾う(self) -> None:
        items = list(self.found["outside_diff"].values())
        self.assertEqual(len(items), 2)
        self.assertEqual(
            [(i["path"], i["line"]) for i in items],
            [
                ("scripts/record-results.ts", "198-230"),
                ("src/web/pages/orders/OrderSection.tsx", "167-174"),
            ],
        )
        self.assertEqual(items[0]["severity"], "🟠 Major")
        self.assertEqual(items[0]["title"], "担当列を条件付きで保護してから書き込む。")
        self.assertEqual(items[0]["fingerprint"], "dcd0c0c176d47a161c8614d9")

    def test_見出しにcodeを含む項目もパスを取り違えない(self) -> None:
        items = list(self.found["outside_diff"].values())
        self.assertEqual(items[1]["path"], "src/web/pages/orders/OrderSection.tsx")

    def test_節の外の畳みを読み込まない(self) -> None:
        """節の直後の "Prompt for all review comments" を項目として数えない。"""
        self.assertEqual(len(self.found["outside_diff"]), 2)
        self.assertEqual(self.found["nitpick"], {})


class PathLineFormTest(unittest.TestCase):
    """項目の先頭行が `パス:行` の形。"""

    def setUp(self) -> None:
        self.found = findings(PATH_LINE_FORM)

    def test_outside_diff_1件を拾う(self) -> None:
        items = list(self.found["outside_diff"].values())
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["path"], items[0]["line"]), ("docs/flow/SKILL.md", "28-31"))
        self.assertEqual(items[0]["severity"], "🟡 Minor")
        self.assertEqual(items[0]["title"], "worktree の分岐を `branch-setup` に委譲してください。")
        self.assertEqual(items[0]["fingerprint"], "318a31cf5cd8404e051971f5")

    def test_節の終わりをPrompt_to_fixの畳みで打ち切る(self) -> None:
        text = strip_blockquote(PATH_LINE_FORM)
        start, end = section_span(text, SECTION_MARKERS["outside_diff"])
        self.assertNotIn("Prompt to fix review comments", text[start:end])

    def test_本文中のコードスパンだけの行を次の項目と取り違えない(self) -> None:
        """関連箇所を `パス:行` だけの行で示しても、元の項目のフィンガープリントを奪わない。"""
        body = PATH_LINE_FORM.replace(
            "> 両方の手順を満たす順序がありません。\n",
            "> 両方の手順を満たす順序がありません。\n>\n> `docs/flow/branch-setup.md:43`\n",
        )
        items = list(findings(body)["outside_diff"].values())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["fingerprint"], "318a31cf5cd8404e051971f5")


class StrongEmphasisFormTest(unittest.TestCase):
    """観点・重大度が太字の形。

    検体は testdata/pr_findings/ にある。`<summary>` の強調が `<strong>`、観点の行が
    `**観点** | **重大度** | **工数**` になり、斜体を前提にした読み取りでは 0 件になる。
    """

    def test_outside_diff_1件のレビューを拾う(self) -> None:
        items = list(findings(body("strong_outside_diff_1.md"))["outside_diff"].values())
        self.assertEqual(
            items,
            [
                {
                    "path": "src/server/errors/order.go",
                    "line": "53-56",
                    "severity": "🟡 Minor",
                    "title": "`cancelled` 状態を含む文言に修正してください。",
                    "fingerprint": "5f1c0a9d2e7b4c6a8d3e1f20",
                }
            ],
        )

    def test_outside_diff_5件のレビューを1件ずつ拾う(self) -> None:
        items = list(findings(body("strong_outside_diff_5.md"))["outside_diff"].values())
        self.assertEqual(
            [(i["path"], i["line"], i["fingerprint"]) for i in items],
            [
                ("src/server/errors/invoice.go", "107-110", "a41e7c2b9d0f3e5a6c8b1d47"),
                ("src/server/errors/payment.go", "97-99", "b52f8d3c0e1a4f6b7d9c2e58"),
                ("src/server/errors/shipment.go", "116-120", "c63a9e4d1f2b5a7c8e0d3f69"),
                ("src/server/errors/shipment.go", "132-136", "d74b0f5e2a3c6b8d9f1e4a70"),
                ("src/server/errors/refund.go", "108-112", "e85c1a6f3b4d7c9e0a2f5b81"),
            ],
        )
        self.assertEqual({i["severity"] for i in items}, {"🟡 Minor"})

    def test_見出しを観点の行と取り違えない(self) -> None:
        """観点の行も行頭の太字で始まる。見出しは、その次の太字から取る。"""
        items = list(findings(body("strong_outside_diff_5.md"))["outside_diff"].values())
        self.assertEqual(items[0]["title"], "更新理由に合うエラー文言に変更してください。")
        self.assertEqual(items[3]["title"], "`ErrShipmentUpdateNotAllowed` の文言を更新してください。")

    def test_2回のレビューの和集合は6件になる(self) -> None:
        found = findings(body("strong_outside_diff_1.md"), body("strong_outside_diff_5.md"))
        self.assertEqual(len(found["outside_diff"]), 6)
        self.assertEqual(found["nitpick"], {})

    def test_nitpickの重大度も太字から読む(self) -> None:
        """Nitpick は畳み形式のまま、観点の行だけが太字に変わる。"""
        items = list(findings(body("strong_nitpick.md"))["nitpick"].values())
        self.assertEqual(
            items,
            [
                {
                    "path": "src/web/pages/orders/OrderSection.tsx",
                    "line": "147-147",
                    "severity": "🔵 Trivial",
                    "title": "`#222222` を共有トークンに置き換えてください。",
                    "fingerprint": "f96d2b7a4c5e8d0f1b3a6c92",
                }
            ],
        )


class ColonCountFormTest(unittest.TestCase):
    """件数がコロンの後ろに付く形。

    検体は testdata/pr_findings/ にある。節の見出しが `Nitpick comments: 1`、ファイルの畳みが
    `パス: 1` になり、括弧の件数を前提にした読み取りでは 0 件になる。
    観点の行は `**📐 Maintainability & Code Quality** | **🔵 Trivial** | **💤 Low value**` である。
    """

    def test_nitpick1件を拾う(self) -> None:
        items = list(findings(body("colon_count_nitpick.md"))["nitpick"].values())
        self.assertEqual(
            items,
            [
                {
                    "path": "src/web/lib/confirm-dialog-action.ts",
                    "line": "47-68",
                    "severity": "🔵 Trivial",
                    "title": "`reload` の失敗が `run` の呼び出し元へ伝わる点を確認してください。",
                    "fingerprint": "0a7e3c8b5d6f9e1a2c4b7d03",
                }
            ],
        )

    def test_括弧の件数の形と混在してもOutside_diffを拾う(self) -> None:
        """Outside diff が `: N`、Nitpick が `(N)` の形でも、古い形式を壊さず読む。"""
        colon = body("colon_count_nitpick.md").replace("🧹 Nitpick comments: 1", "⚠️ Outside diff range comments: 1")
        found = findings(colon, DETAILS_FORM)
        self.assertEqual(len(found["outside_diff"]), 3)
        self.assertEqual(len(found["nitpick"]), 1)

    def test_節の外の畳みを読み込まない(self) -> None:
        found = findings(body("colon_count_nitpick.md"))
        self.assertEqual(len(found["nitpick"]), 1)
        self.assertEqual(found["outside_diff"], {})


class MixedTest(unittest.TestCase):
    def test_形式が混在しても和集合になる(self) -> None:
        found = findings(DETAILS_FORM, BLOCKQUOTE_FORM, body("strong_outside_diff_1.md"))
        self.assertEqual(len(found["outside_diff"]), 5)
        self.assertEqual(len(found["nitpick"]), 1)

    def test_CodeRabbit以外のレビューは読まない(self) -> None:
        reviews = [{"user": {"login": "someone"}, "body": BLOCKQUOTE_FORM}]
        self.assertEqual(collect_body_findings(reviews)["outside_diff"], {})


if __name__ == "__main__":
    unittest.main()

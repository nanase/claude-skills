# pr-review-loop — CodeRabbit 固有の扱い

[pr-review-loop](SKILL.md) のループを CodeRabbit が付く PR で回すときの、この bot 固有の挙動である。一般の作法は SKILL.md にある。

## レビューの所在

- review 本文には複数の `<details>` が畳まれる（`Nitpick comments (N)`・`Outside diff range comments (N)`・`Additional comments` など）
  - `read-reviews.sh` の出力にそのまま含まれるので、タイトル別にすべて開いて読む
- `Outside diff range comments` を特に取りこぼしやすい
  - diff 外の行への指摘なので区画 2（インライン）に出ず、区画 1（review 本文）の畳みの中だけに在る
  - nitpick とは別枠で対応を要する指摘を含むので、nitpick と同じ軽さで流さない
  - 目視・インラインだけ見ると構造的に取りこぼす
    - `scripts/pr-findings.sh` で機械的に列挙し、未対応 0 件を確認する
- 節の書かれ方に 2 形式あり、太字形式には項目の先頭行の違いがもう 1 つある
  - 畳み形式は `<summary>⚠️ Outside diff range comments (N)</summary>` で始まり、対象ファイルごとに `<summary>パス (N)</summary>` でまとめる
  - 太字形式は「インラインに出せない」旨の `[!CAUTION]` に続き、引用ブロックの中の `> **⚠️ Outside diff range comments (N)**` で始まる
    - ファイルのまとめ役が無く、パスは項目ごとの `<summary>` 末尾の `<code>パス:行</code>` に入る
    - 項目の先頭行が `` `パス:行` `` だけで、観点・重大度が次の行に続くこともある。このとき `<summary>` 末尾の `<code>` はファイル名だけになる
  - 観点・重大度の行の強調も 2 形式ある
    - 斜体は `_観点_ | _重大度_`、太字は `**観点** | **重大度** | **工数**` である。太字の形では `<summary>` の強調も `<em>` から `<strong>` に変わる
    - 畳み形式の Nitpick も、観点の行だけ太字になることがある
  - 件数の書き方も 2 形式ある。`(N)` と、`Nitpick comments: N`・`パス: N` である
  - `pr_findings.py` はどの形も読む
    - 形式を取りこぼすと、指摘が残っていても未対応 0 件と数える
    - 形式は予告なく変わり、変わった直後のレビューから旧形式の読み取りでは 0 件になる
    - 見たことのない形式に出会ったら `scripts/pr_findings_test.py` に検体を足し、`python3 scripts/pr_findings_test.py` で全形式が通ることを確かめる
- 本文項目には resolved の概念が無い
  - `auto_incremental_review` は前回レビュー以降の差分しか見ないため、後続レビューに再掲されないことは対応済みを意味しない
  - `pr-findings.sh` は全レビュー本文のフィンガープリントの和集合を「一度でも指摘された項目」として扱う
    - 対応した PR コメントにそのフィンガープリント（`cr-comment:v1:HASH`）を含めて初めて対応済みと判定する
- 指摘 0 件のときは review 本文自体を作らない
  - `gh api .../pulls/{n}/reviews` の件数だけを「レビュー済みか」の判定に使うと、投稿済みでも 0 件のまま待ち続ける
  - `read-reviews.sh` の区画 0 に出す CodeRabbit のコミットステータス（`gh pr checks` の CodeRabbit 行と同じ情報源）を合わせて見る
  - ステータスが `queued` / `in progress` の間はレビュー中
  - `success` になれば review 本文が無くても指摘 0 件のレビュー済みとして扱う
  - `failure` / `error` / ステータスなしは、review 本文が無くても「完了」の根拠にせず要確認へ回す（正常終了の保証が無いため）
- サマリは PR 先頭コメントを上書き更新する
  - 毎回最新を読み直す
  - docstring 不足・PR 説明文の乖離・テスト不足などのメタ警告が混じる
  - PR の質に直結するので拾い、PR の本文や docstring を直す

## スキップと未解決表示

対応・返信も済んでいるスレッドが、bot 側の再走査で「前回と類似」としてファイルをスキップされ、未解決の表示だけ残ることがある。

- この場合は無理に resolve しない
- 当該スレッドに対応内容を書き足す
- 見送った点があれば、その理由も書き足す
- bot がスキップした旨も書き足す

## 初回レビューの起点は Ready 化

`.coderabbit.yaml` の `reviews.auto_review.drafts` は既定で `false` なので、draft の PR はレビューされない。draft を Ready にした時点が第 1 巡になる。

- CI がグリーンになり、自己レビューと PR 本文の確定が済んでから Ready にする
  - レビューは確定した差分に対して 1 回だけ走り、CI の修正 push でレビュー回数を消費しない
- ループは Ready 化の後から回す
  - draft のまま回すと、レビューが来ない状態でポーリングし続けることになる

## 返信

対応しない指摘には `@coderabbitai` をメンションして理由を返すと、撤回・メモリ更新で応じる。

## 増分レビュー

- push そのものが増分レビューの起点であり、枠を消費する
  - 指摘への修正を 1 件ずつ push すると、その都度枠を消費する
  - まとめて 1 回の push にする
- push 後に `@coderabbitai review` を送らない
  - push ごとに自動で増分レビューが走るため、手動で送ると二重に走り使用量を無駄にする
  - push したら自動レビューを待つ
- 手動で促してよい例外は 3 つある
  - いずれも自動レビューが走っていないことを先に確かめてから送る

手動で促してよい 3 つは次のとおり。

- 一時停止された
  - 一定のコミット数で増分レビューが止まる
  - サマリに一時停止の旨が出ていたら `@coderabbitai review` で再開を促す
- レート制限で開始できなかった
  - サマリに "Review limit reached" と解除までの分数が出ている
  - 手順は次の「レート制限」節に従う
  - 分数が明記されているので、根拠なく数巡待つ必要はない
- それ以外の理由で数巡待っても走らない
  - 上記いずれのメッセージも出ないまま、障害などで理由不明に HEAD へのレビューが付かないとき
  - 促しても来なければ、判定表「完了」が前提とする HEAD レビューの例外として、push 前の自己レビューと CI（未対応の指摘なし・全て成功・マージ可能）を根拠に完了してよい

## レート制限（Review limit reached）

CodeRabbit の 1 時間あたりのレビュー回数制限に当たると、サマリ（PR 先頭コメント）に「Review limit reached」の警告と解除までの分数が出て、レビューが始まらない。制限に当たるたびに同じサマリが上書きされ、分数も変わる。

このメッセージが出ている間は待つしかない。解除時刻を過ぎても、時間の経過だけでは自動的に再試行されない。後述のとおり `@coderabbitai review` で明示的に依頼して初めてレビューが始まる。

同じメッセージに「Run on-demand review」のチェックボックスが並ぶことがある。従量課金でレビューを走らせるもので、課金するかはユーザーが決める。押さず、押すよう勧めもしない。

文面は CodeRabbit 側の都合で何度も変わってきた。文面を当てにせず、判定と解除時刻の計算は `scripts/rate-limit-status.sh [PR番号]` に任せる。自分で分数を読んで計算しない。出力は次の 3 通りである。

- `STATUS=no_limit`
  - 制限メッセージが無く、通常のループへ戻ってよい
- `STATUS=ready`
  - 解除時刻を過ぎているので、そのまま次に進んでよい
- `STATUS=waiting REMAINING_SECONDS=S DEADLINE=...`
  - 解除まで S 秒残っている

`ready` と `waiting` には、制限を何で見つけたか（`DETECTED_BY`）と、解除時刻の根拠（`BASIS`）が付く。

- `DETECTED_BY=marker`
  - CodeRabbit が埋め込む印で見つけた。通常はこちらである
- `DETECTED_BY=heading`
  - 印が無く、「Review limit reached」の見出しで見つけた
  - 印の付け方が変わった疑いがあるので、待機とあわせて人へ知らせる
- `BASIS=displayed`
  - 表示された分数 `MINUTES` から計算した。切り捨ての誤差を吸収する数分の余裕を、`DEADLINE`・`REMAINING_SECONDS` に反映済みである
- `BASIS=default`
  - 分数を読めず（`MINUTES=unknown`）、既定の待ち時間 60 分で解除時刻を計算した
  - 文面が変わった疑いがあるので、待機とあわせて人へ知らせる

委譲を受けて動いているときは、この節の待機と再依頼を自分で行わない。`MINUTES`・`BASIS`・`DETECTED_BY`・`UPDATED_AT` を委譲元へ報告し、再レビュー依頼の指示を待つ。`BASIS=default` のときは、解除までの時間が不明であることを明記する。空いた枠をどの PR へ与えるかは委譲元が決めるためである。

`STATUS=waiting` の間の待ち方と、`STATUS=ready` になってからの動きは次のとおり。

- `REMAINING_SECONDS` だけ `ScheduleWakeup` で待つ
  - 1 回の delaySeconds は 3300 秒までにする。残り時間がそれを超える場合は 3300 秒で一旦起き、`rate-limit-status.sh` を再実行して残り時間を計算し直す
    - 起床は頼んだ時刻より遅れることがあり、3600 秒ではプロンプトキャッシュの有効期限（1 時間）を過ぎて起きうるため
  - この中間ウェイクは `noop: true` にする
  - この待機は SKILL.md の判定表の「待機中」に当たるが、通常のポーリング間隔（360/330/240 秒）ではなく解除時刻ベースで待つ
- 解除時刻を過ぎたら PR コメントとして `@coderabbitai review` を送り、レビューを依頼する
  - 送った直後にもう一度 `rate-limit-status.sh` を実行する
  - 新しい `updated_at` と分数で `STATUS=waiting` に戻っていたら、順番待ちで再び制限に当たったということなので同じ手順で待ち直す

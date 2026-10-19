#!/usr/bin/env bash
# rate-limit-status.sh — CodeRabbit のレート制限（Review limit reached）の解除待ちを判定する。
#
# 使い方: rate-limit-status.sh [PR番号]
#   PR 番号を省略すると現在のブランチの PR を使う。
#
# このシェルは PR コメントを取ってくる入口で、判定は rate_limit_status.py が行う。
# 制限中かどうかは文章でなく CodeRabbit が埋め込む HTML コメントの印で決め、分数は読めたときだけ使う。
# 経緯と考え方は rate_limit_status.py の冒頭にある。
#
# 依存: gh / python3。python3 が無い環境では終了 3 で止まる。
#
# 出力は標準出力に key=value の行で出す。キーと読み方は ../CODERABBIT.md の「レート制限」節にある。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "python3 が見つかりません。PR のサマリ（CodeRabbit の先頭コメント）を開き、制限メッセージの有無と分数を目視で確かめてください。" >&2
  exit 3
}
R="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
PR="${1:-$(gh pr view --json number -q .number)}"

# PR 番号は API パスに埋め込むため数値のみ許可する。
[[ "$PR" =~ ^[0-9]+$ ]] || { echo "PR 番号は数値で渡してください（現在: $PR）" >&2; exit 2; }

# 全ページを束ねて渡す。ページごとの配列の平坦化は rate_limit_status.py が行う。
gh api "repos/$R/issues/$PR/comments" --paginate --slurp | python3 "$SCRIPT_DIR/rate_limit_status.py"

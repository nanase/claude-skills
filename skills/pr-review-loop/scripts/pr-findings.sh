#!/usr/bin/env bash
# pr-findings.sh — PR の指摘（インライン・review 本文の Outside diff / Nitpick）を
# 漏れなく列挙し、未対応だけを抽出する。read-reviews.sh の後継。
#
# 使い方: pr-findings.sh [PR番号]
#   PR 番号を省略すると現在のブランチの PR を使う。
#
# 本文項目（Outside diff / Nitpick）には GitHub 側に「対応済み」概念が無く、
# 増分レビューは差分に触れた指摘しか再掲しない。そのため全レビュー本文の和集合を
# 「一度でも指摘された項目」とし、PR コメントでのフィンガープリント（cr-comment:v1:HASH）
# 言及の有無で対応済みを判定する。指摘に対応したら、その PR コメントにフィンガープリントを
# 含めること。
#
# 依存: gh / jq / python3。集計は畳まれた HTML の入れ子を解くため python3 に委ねている。
# python3 が無い環境では終了 3 で止まる。その場合は read-reviews.sh の区画 1 を目視で開いて
# 読む運用に落ちる（スキル本文の指示に従う）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "python3 が見つかりません。read-reviews.sh の目視確認へフォールバックしてください。" >&2
  exit 3
}
R="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
OWNER="${R%/*}"
REPO="${R#*/}"
PR="${1:-$(gh pr view --json number -q .number)}"

[[ "$PR" =~ ^[0-9]+$ ]] || { echo "PR 番号は数値で渡してください（現在: $PR）" >&2; exit 2; }

# jq --argjson はコマンドライン引数として渡るため OS の ARG_MAX の対象になり、
# レビュー本文が肥大化すると "Argument list too long" で落ちる。--slurpfile は
# ファイル経由で読み込むため ARG_MAX の制限を受けない。
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

reviews_file="$tmpdir/reviews.json"
inline_comments_file="$tmpdir/inline_comments.json"
issue_comments_file="$tmpdir/issue_comments.json"
resolved_map_file="$tmpdir/resolved_map.json"

gh api "repos/$R/pulls/$PR/reviews" --paginate --slurp | jq -c 'add' > "$reviews_file"
gh api "repos/$R/pulls/$PR/comments" --paginate --slurp | jq -c 'add' > "$inline_comments_file"
gh api "repos/$R/issues/$PR/comments" --paginate --slurp | jq -c 'add' > "$issue_comments_file"

# reviewThreads の isResolved を databaseId（REST のインラインコメント id）にマップする。
gh api graphql --paginate --slurp -f query='
  query($owner:String!, $repo:String!, $pr:Int!, $endCursor:String) {
    repository(owner:$owner, name:$repo) {
      pullRequest(number:$pr) {
        reviewThreads(first: 50, after: $endCursor) {
          pageInfo { hasNextPage endCursor }
          nodes {
            isResolved
            comments(first: 50) { nodes { databaseId } }
          }
        }
      }
    }
  }' -f owner="$OWNER" -f repo="$REPO" -F pr="$PR" \
  | jq -c '[.[].data.repository.pullRequest.reviewThreads.nodes[]?]
      | map(. as $t | .comments.nodes[] | {(.databaseId|tostring): $t.isResolved})
      | add // {}' > "$resolved_map_file"

jq -n \
  --slurpfile reviews "$reviews_file" \
  --slurpfile inline_comments "$inline_comments_file" \
  --slurpfile issue_comments "$issue_comments_file" \
  --slurpfile resolved_map "$resolved_map_file" \
  '{reviews:$reviews[0], inline_comments:$inline_comments[0], issue_comments:$issue_comments[0], resolved_map:$resolved_map[0]}' \
  | python3 "$SCRIPT_DIR/pr_findings.py"

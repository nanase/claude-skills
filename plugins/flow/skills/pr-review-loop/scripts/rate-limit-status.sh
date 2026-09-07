#!/usr/bin/env bash
# rate-limit-status.sh — CodeRabbit のレート制限（Review limit reached）の解除待ちを判定する。
#
# 使い方: rate-limit-status.sh [PR番号]
#   PR 番号を省略すると現在のブランチの PR を使う。
#
# サマリ（PR 先頭コメント）は制限に当たるたびに上書き更新され、"Next included
# review available in 55 minutes." のような分数が出る。解除時刻は経過時間で
# 数えず、常にそのコメントの updated_at を起点に計算し直す（何度待ち直しても
# 正確）。
#
# 文面は CodeRabbit 側の都合で動く。"Next review available in:** **43 minutes**"
# だったものが "Next included review available in 55 minutes." になった。語が
# 増え、コロンが消え、強調の位置が変わっている。分数の読み取りが止まると、
# ループはそこで進めなくなる。強調とコロンを先に落としてから読むことで、
# 語順が同じかぎりどちらの文面でも同じ式が当たる。
#
# ただし N は分単位で切り捨てられており秒の情報が無いため、計算した解除時刻は
# 実際より最大 1 分弱早くなりうる。これに当たると促しが早すぎて「数秒待て」と
# 返されるだけでなく、複数 PR が順番待ちしている場合は待ち直しになり被害が大きい
# ので、BUFFER_MINUTES ぶん余分に待って解除時刻を後ろにずらす。
#
# 依存は gh・bash と、base64・tr・date に絞ってある。時刻の計算に GNU coreutils の
# `date -d` を使うと macOS・Windows で動かないため、ISO8601 の解釈と整形はシェルの
# 算術で行う。現在時刻の取得に使う `date -u +%s` はどの環境でも同じ意味を持つ。
# base64 だけは移植性が完全ではない。復号の指定は GNU なら `-d`、BSD の古い版は `-D`
# である。動かない環境に当たったらここを疑う。
#
# 出力（標準出力、key=value）:
#   STATUS=no_limit                                  制限メッセージが無い。通常のループへ
#   STATUS=ready   MINUTES=N UPDATED_AT=...           解除時刻を過ぎている。促してよい
#   STATUS=waiting REMAINING_SECONDS=S DEADLINE=... MINUTES=N UPDATED_AT=...
#                                                      解除時刻まで S 秒残っている
set -euo pipefail

# 解除時刻の分数表示は切り捨てなので、その誤差を吸収するための余分な待ち時間。
BUFFER_MINUTES=3

# days_from_civil / civil_from_days — 暦日と 1970-01-01 起点の通日を相互変換する。
# うるう年の規則をそのまま式にしたもので、外部コマンドを使わずに済む。
days_from_civil() {
  local y=$1 m=$2 d=$3 era yoe doy doe
  (( m <= 2 )) && (( y -= 1 ))
  era=$(( y / 400 ))
  yoe=$(( y - era * 400 ))
  if (( m > 2 )); then
    doy=$(( (153 * (m - 3) + 2) / 5 + d - 1 ))
  else
    doy=$(( (153 * (m + 9) + 2) / 5 + d - 1 ))
  fi
  doe=$(( yoe * 365 + yoe / 4 - yoe / 100 + doy ))
  echo $(( era * 146097 + doe - 719468 ))
}

civil_from_days() {
  local z=$1 era doe yoe y doy mp d m
  z=$(( z + 719468 ))
  era=$(( z / 146097 ))
  doe=$(( z - era * 146097 ))
  yoe=$(( (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365 ))
  y=$(( yoe + era * 400 ))
  doy=$(( doe - (365 * yoe + yoe / 4 - yoe / 100) ))
  mp=$(( (5 * doy + 2) / 153 ))
  d=$(( doy - (153 * mp + 2) / 5 + 1 ))
  if (( mp < 10 )); then m=$(( mp + 3 )); else m=$(( mp - 9 )); fi
  (( m <= 2 )) && (( y += 1 ))
  echo "$y $m $d"
}

# GitHub の timestamp は必ず UTC の ISO8601（例 2026-08-25T16:35:06Z）で返る。
iso_to_epoch() {
  local ts=$1
  [[ "$ts" =~ ^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2}) ]] || {
    echo "timestamp を解釈できませんでした（現在: $ts）" >&2
    exit 2
  }
  local days
  days=$(days_from_civil "$((10#${BASH_REMATCH[1]}))" "$((10#${BASH_REMATCH[2]}))" "$((10#${BASH_REMATCH[3]}))")
  echo $(( days * 86400 + 10#${BASH_REMATCH[4]} * 3600 + 10#${BASH_REMATCH[5]} * 60 + 10#${BASH_REMATCH[6]} ))
}

epoch_to_iso() {
  local e=$1 days secs y m d
  days=$(( e / 86400 ))
  secs=$(( e % 86400 ))
  if (( secs < 0 )); then days=$(( days - 1 )); secs=$(( secs + 86400 )); fi
  read -r y m d <<< "$(civil_from_days "$days")"
  printf '%04d-%02d-%02dT%02d:%02d:%02dZ\n' \
    "$y" "$m" "$d" "$(( secs / 3600 ))" "$(( secs % 3600 / 60 ))" "$(( secs % 60 ))"
}

R="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
PR="${1:-$(gh pr view --json number -q .number)}"

# PR 番号は API パスに埋め込むため数値のみ許可する。
[[ "$PR" =~ ^[0-9]+$ ]] || { echo "PR 番号は数値で渡してください（現在: $PR）" >&2; exit 2; }

# 制限メッセージを含むコメントのうち最新（updated_at 最大）のものを 1 件選ぶ。
# 同じコメントが繰り返し上書きされるため、複数該当しても最新だけを見ればよい。
LATEST="$(gh api "repos/$R/issues/$PR/comments" --paginate --jq '
  [.[] | select(.body | contains("Review limit reached"))]
  | sort_by(.updated_at)
  | last
  | if . == null then empty else "\(.updated_at)\t\(.body | @base64)" end
')"

if [[ -z "$LATEST" ]]; then
  echo "STATUS=no_limit"
  exit 0
fi

UPDATED_AT="${LATEST%%$'\t'*}"
BODY="$(echo "${LATEST#*$'\t'}" | base64 -d)"

# 強調の `*` とコロンは文面が変わるたびに位置が動くので、読む前に落とす。残る
# のは語順だけで、次のどちらも同じ形になる。
#   "**Next review available in:** **43 minutes**"
#   "**Next included review available in 55 minutes.**"
FLAT="$(printf '%s' "$BODY" | tr -d '*:')"
RE='Next[[:space:]]+(included[[:space:]]+)?review[[:space:]]+available[[:space:]]+in[[:space:]]+([0-9]+)[[:space:]]*minutes?'
if [[ ! "$FLAT" =~ $RE ]]; then
  echo "レート制限メッセージは見つかりましたが分数を抽出できませんでした。コメントの文言が変わっていないか確認してください。" >&2
  exit 2
fi
MINUTES="${BASH_REMATCH[2]}"

DEADLINE_EPOCH=$(( $(iso_to_epoch "$UPDATED_AT") + (10#$MINUTES + BUFFER_MINUTES) * 60 ))
NOW_EPOCH="$(date -u +%s)"
REMAINING=$(( DEADLINE_EPOCH - NOW_EPOCH ))

if (( REMAINING <= 0 )); then
  echo "STATUS=ready"
  echo "MINUTES=$MINUTES"
  echo "UPDATED_AT=$UPDATED_AT"
else
  echo "STATUS=waiting"
  echo "REMAINING_SECONDS=$REMAINING"
  echo "DEADLINE=$(epoch_to_iso "$DEADLINE_EPOCH")"
  echo "MINUTES=$MINUTES"
  echo "UPDATED_AT=$UPDATED_AT"
fi

#!/usr/bin/env bash
# run.sh — 人が打つコマンドを包み、終わったことを HQ が自動で知れるようにする。
#
# 使い方: run.sh U<番号> [-C <ディレクトリ>] -- <コマンド>...
#   コマンドは引数のまま実行する。パイプや && を使うときは -- bash -c '…' の形で渡す。
#   -C を渡すと、そのディレクトリへ移ってから実行する。
#
# 出力は画面に出しつつ <保管先>/runs/U<番号>.log へ写し、終了コードを U<番号>.exit へ書く。
# 保管先は HQ_STORE で受け取る（台帳が渡すコマンドに付いている）。無ければ _store.sh が決める。
# 終了コードは書き終えてから置くため、HQ の監視が書きかけを読むことはない。
# 端末から打つと、ログには制御文字も残る。
set -uo pipefail

# shellcheck source=_store.sh
. "$(dirname "$0")/_store.sh"

die() { echo "run.sh: $*" >&2; exit 2; }

id=${1:-}
[[ "$id" =~ ^U[0-9]+$ ]] || die "1 つ目の引数は U3 の形の番号です（現在: ${id:-なし}）"
shift
dir=""
if [ "${1:-}" = "-C" ]; then
  dir=${2:-}
  [ -d "$dir" ] || die "-C のディレクトリがありません: $dir"
  shift 2
fi
[ "${1:-}" = "--" ] || die "コマンドの前に -- を置いてください"
shift
[ $# -gt 0 ] || die "コマンドを渡してください"

runs=$(hq_runs_dir)
mkdir -p "$runs"
log="$runs/$id.log"
rm -f "$runs/$id.exit"

if [ -n "$dir" ]; then cd "$dir" || die "-C のディレクトリへ移れません: $dir"; fi
{
  echo "dir: $(pwd)"
  echo "started: $(date '+%F %H:%M:%S %Z')"
  printf 'command:'
  printf ' %q' "$@"
  echo
} > "$runs/$id.cmd"

# Ctrl-C で止められても、終了コードは書き残す。書かないと HQ の監視が待ち続ける。
trap ':' INT

# 端末から打たれたときは script で包み、コマンドからも端末に見えるようにする。
# パイプで tee へ渡すと、gh などが端末でないと見て確認の問いを出さなくなる。
if [ -t 0 ] && [ -t 1 ]; then
  cmdline=$(printf '%q ' "$@")
  SHELL=/bin/bash script -q -e -c "$cmdline" "$log"
  code=$?
else
  "$@" 2>&1 | tee "$log"
  code=${PIPESTATUS[0]}
fi

tmp=$(mktemp "$runs/.exit.XXXXXX")
echo "$code" > "$tmp"
mv "$tmp" "$runs/$id.exit"

echo
if [ "$code" -eq 0 ]; then
  echo "$id は終わりました。HQ が自動で検知するので、連絡は要りません。"
else
  echo "$id は終了コード $code で失敗しました。HQ がログを読んで対処します。"
fi
exit "$code"

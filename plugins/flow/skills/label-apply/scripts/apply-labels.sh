#!/usr/bin/env bash
# 判定済みのラベルを Issue / PR へ付与し、反映後のラベルを出力する。判定は label-apply スキルが行う。
#
# 使い方: apply-labels.sh issue|pr <番号> <ラベル名>...
set -euo pipefail

KIND="${1:-}"
NUMBER="${2:-}"
case "$KIND" in
  issue|pr) ;;
  *) echo "第 1 引数は issue または pr です（現在: ${KIND:-未指定}）" >&2; exit 2 ;;
esac
[[ "$NUMBER" =~ ^[0-9]+$ ]] || { echo "番号は数値で渡してください（現在: ${NUMBER:-未指定}）" >&2; exit 2; }
shift 2
[ "$#" -gt 0 ] || { echo "付けるラベルを 1 つ以上渡してください" >&2; exit 2; }

ARGS=()
for name in "$@"; do ARGS+=(--add-label "$name"); done

gh "$KIND" edit "$NUMBER" "${ARGS[@]}" >/dev/null
gh "$KIND" view "$NUMBER" --json labels -q '.labels[].name'

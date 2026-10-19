#!/usr/bin/env bash
# ledger.sh — HQ の台帳を扱う。子からの報告（R）と、人へのお願い（🙋 U・🔀・🔒・🧹）を 1 件 1 ファイルで持つ。
#
# 使い方:
#   ledger.sh [-l 台帳名] next R|U|S
#       通し番号を 1 つ進めて出す（例: S13）。番号は使い回さない
#   ledger.sh [-l 台帳名] add R <S番号> <見出し>
#       報告を足す。詳細は標準入力から読む。出力は採番した ID
#   ledger.sh [-l 台帳名] add U <S番号> <見出し> (-C <ディレクトリ> | --host) -- <コマンド>...
#       人に打ってもらうコマンドを足す。-C は HQ と同じ環境で打つ場所で、run.sh 経由の形にする
#       --host は HQ からファイルが見えない別の環境で打つもので、ファイルが見えないため自動では検知しない
#   ledger.sh [-l 台帳名] add merge <S番号> <PR番号>
#   ledger.sh [-l 台帳名] add close <S番号|-> <issue番号>
#   ledger.sh [-l 台帳名] add cleanup <S番号> <セッション名>
#       セッション名は ListAgents の名前。登録簿から pid を引いて持ち、名前が変わっても追える
#   ledger.sh [-l 台帳名] list R
#       未解決の報告を「- R3 ⏸ S2 見出し」の形で出す。⏸ は子が人の判断を待って止まっているもの
#   ledger.sh [-l 台帳名] list ask
#       未解決のお願いを、報告の「お願いしたいこと」へそのまま貼れる Markdown で出す
#   ledger.sh [-l 台帳名] show <ID>
#   ledger.sh [-l 台帳名] set <ID> open|wait|done
#       wait は ⏸、done は解決。解決したものは list に出ない
#
# ID は R3・U3 のほか、merge-103・close-42・cleanup-S9 の形をとる。
# 保管先は _store.sh を参照。台帳は <保管先>/ledger/<台帳名>/、通し番号は <保管先>/counters/ に置く。
# 通し番号のファイルは最後に使った番号を 1 行で持つ。
set -euo pipefail

# shellcheck source=_store.sh
. "$(dirname "$0")/_store.sh"

die() { echo "ledger.sh: $*" >&2; exit 2; }

if [ "${1:-}" = "-l" ]; then
  [ -n "${2:-}" ] || die "-l には台帳名を渡してください"
  hq_ledger_name=$2
  shift 2
fi

ledger=$(hq_ledger_dir)
mkdir -p "$ledger" "$HQ_STORE/counters"

now() { date '+%F %H:%M %Z'; }

next_id() {
  local kind=$1 file n
  [[ "$kind" =~ ^[RUS]$ ]] || die "番号の種類は R・U・S のどれかです（現在: $kind）"
  file="$HQ_STORE/counters/$kind"
  exec 9>"$HQ_STORE/counters/.lock"
  flock 9
  n=$(cat "$file" 2>/dev/null || echo 0)
  n=$((n + 1))
  echo "$n" > "$file"
  exec 9>&-
  printf '%s%s\n' "$kind" "$n"
}

check_sid() { [[ "$1" =~ ^S[0-9]+$ ]] || [ "$1" = "-" ] || die "S番号は S12 の形で渡してください（現在: $1）"; }

set_state() {
  local file="$ledger/$1.md" tmp
  [ -f "$file" ] || die "$1 は台帳にありません"
  tmp=$(mktemp "$ledger/.tmp.XXXXXX")
  awk -v s="$2" 'NR==1 && $0=="---" {f=1; print; next} f && $0=="---" {f=0} f && /^state: / {print "state: " s; next} {print}' "$file" > "$tmp"
  mv "$tmp" "$file"
}

# 打つ人がそのまま貼れるように、引数を必要なときだけ単一引用符で囲む。
quote_args() {
  local out="" a
  for a in "$@"; do
    if [[ "$a" =~ ^[A-Za-z0-9_./:=@%+,-]+$ ]]; then
      out+=" $a"
    else
      out+=" '${a//\'/\'\\\'\'}'"
    fi
  done
  printf '%s' "${out# }"
}

write_item() {
  # 引数: ID 種類 S番号 見出し、続けて追加の「キー: 値」行。本文は標準入力から読む
  local id=$1 kind=$2 sid=$3 title=$4 file
  shift 4
  file="$ledger/$id.md"
  # 同じ PR・issue・S番号のお願いを足し直したときは、古い中身を残さず書き直す。
  # 🧹 の pid が古いまま残ると、生きているセッションを閉じたと取り違える。
  {
    echo "---"
    echo "id: $id"
    echo "kind: $kind"
    echo "session: $sid"
    echo "title: $title"
    echo "state: open"
    echo "created: $(now)"
    local line
    for line in "$@"; do echo "$line"; done
    echo "---"
    cat
  } > "$file"
  echo "$id"
}

add() {
  local kind=${1:-} sid=${2:-}
  [ -n "$kind" ] && [ -n "$sid" ] || die "add には種類と S番号を渡してください"
  check_sid "$sid"
  shift 2
  # 採番より前に弾く。弾いた件に番号を使わないため
  [[ "$*" != *$'\n'* ]] || die "見出しとコマンドに改行を入れないでください。台帳の 1 行に収まらなくなります"
  case "$kind" in
    R)
      [ -n "${1:-}" ] || die "見出しを渡してください"
      write_item "$(next_id R)" R "$sid" "$1"
      ;;
    U)
      local title=${1:-} dir="" host=""
      [ -n "$title" ] || die "見出しを渡してください"
      shift
      while [ $# -gt 0 ] && [ "$1" != "--" ]; do
        case "$1" in
          -C) dir=${2:-}; shift 2 ;;
          --host) host=1; shift ;;
          *) die "add U の引数が読めません: $1" ;;
        esac
      done
      [ "${1:-}" = "--" ] || die "コマンドの前に -- を置いてください"
      shift
      [ $# -gt 0 ] || die "コマンドを渡してください"
      [ -n "$dir" ] || [ -n "$host" ] || die "-C <打つ場所> か --host のどちらかを渡してください"
      local id cmd
      id=$(next_id U)
      if [ -n "$host" ]; then
        cmd=$(quote_args "$@")
        write_item "$id" U "$sid" "$title" "place: host" "command: $cmd" < /dev/null
      else
        # どこで打たれても HQ の保管先へ書くよう、保管先を前に付けて渡す
        cmd=$(quote_args "HQ_STORE=$HQ_STORE" "$hq_script_dir/run.sh" "$id" -C "$dir" -- "$@")
        write_item "$id" U "$sid" "$title" "place: local" "command: $cmd" < /dev/null
      fi
      ;;
    merge)
      [[ "${1:-}" =~ ^[0-9]+$ ]] || die "PR 番号を渡してください"
      write_item "merge-$1" merge "$sid" "#$1 のマージ" "target: $1" < /dev/null
      ;;
    close)
      [[ "${1:-}" =~ ^[0-9]+$ ]] || die "issue 番号を渡してください"
      write_item "close-$1" close "$sid" "#$1 のクローズ" "target: $1" < /dev/null
      ;;
    cleanup)
      [ "$sid" != "-" ] || die "cleanup には S番号が要ります"
      local name=${1:-} f pid start
      [ -n "$name" ] || die "セッション名を渡してください"
      pid=""
      for f in "$HQ_SESSIONS_DIR"/*.json; do
        [ -f "$f" ] || continue
        [ "$(jq -r '.name // empty' "$f")" = "$name" ] || continue
        start=$(jq -r '.procStart // empty' "$f")
        local p
        p=$(jq -r '.pid // empty' "$f")
        if [ -n "$p" ] && [ "$(hq_proc_start "$p")" = "$start" ]; then pid=$p; break; fi
      done
      [ -n "$pid" ] || die "$name は登録簿に生きたセッションとして見つかりません。既に閉じている可能性があります"
      write_item "cleanup-$sid" cleanup "$sid" "$sid のセッションを閉じる" "target: $name" "pid: $pid" "procstart: $start" < /dev/null
      ;;
    *) die "種類は R・U・merge・close・cleanup のどれかです（現在: $kind）" ;;
  esac
}

# 未解決の項目を、ID の番号順で 1 行 1 ファイルのパスとして出す。
open_items() {
  local f state
  for f in "$ledger"/$1*.md; do
    [ -f "$f" ] || continue
    state=$(hq_field "$f" state)
    [ "$state" = done ] && continue
    printf '%s\n' "$f"
  done | sort -V
}

list() {
  local f
  case "${1:-}" in
    R)
      while IFS= read -r f; do
        local mark=""
        [ "$(hq_field "$f" state)" = wait ] && mark=" ⏸"
        printf -- '- %s%s %s %s\n' "$(hq_field "$f" id)" "$mark" "$(hq_field "$f" session)" "$(hq_field "$f" title)"
      done < <(open_items R)
      ;;
    ask)
      while IFS= read -r f; do
        local note=""
        [ "$(hq_field "$f" place)" = host ] && note="（別の環境で打ち、終わったら「$(hq_field "$f" id) 打った」と伝えてください）"
        printf -- '- 🙋 %s %s %s%s\n\n  ```sh\n  %s\n  ```\n\n' "$(hq_field "$f" id)" "$(hq_field "$f" session)" "$(hq_field "$f" title)" "$note" "$(hq_field "$f" command)"
      done < <(open_items U)
      while IFS= read -r f; do
        printf -- '- 🔀 %s（%s）\n' "$(hq_field "$f" title)" "$(hq_field "$f" session)"
      done < <(open_items merge-)
      while IFS= read -r f; do
        local s
        s=$(hq_field "$f" session)
        if [ "$s" = "-" ]; then printf -- '- 🔒 %s\n' "$(hq_field "$f" title)"; else printf -- '- 🔒 %s（%s）\n' "$(hq_field "$f" title)" "$s"; fi
      done < <(open_items close-)
      while IFS= read -r f; do
        printf -- '- 🧹 %s\n' "$(hq_field "$f" title)"
      done < <(open_items cleanup-)
      ;;
    *) die "list には R か ask を渡してください" ;;
  esac
}

cmd=${1:-}
[ -n "$cmd" ] || die "サブコマンドを渡してください（next・add・list・show・set）"
shift
case "$cmd" in
  next) next_id "${1:-}" ;;
  add) add "$@" ;;
  list) list "$@" ;;
  show)
    [ -f "$ledger/${1:-}.md" ] || die "${1:-} は台帳にありません"
    cat "$ledger/$1.md"
    ;;
  set)
    [[ "${2:-}" =~ ^(open|wait|done)$ ]] || die "状態は open・wait・done のどれかです"
    set_state "${1:-}" "$2"
    ;;
  *) die "サブコマンドは next・add・list・show・set のどれかです（現在: $cmd）" ;;
esac

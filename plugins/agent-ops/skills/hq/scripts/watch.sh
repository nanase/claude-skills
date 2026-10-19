#!/usr/bin/env bash
# watch.sh — 台帳の未解決のお願いを見張り、どれかが片付いたら知らせて終わる。
#
# 使い方:
#   watch.sh [-l 台帳名]            見張る。HQ は Bash の run_in_background で走らせる
#   watch.sh [-l 台帳名] --status   見張りが動いているかだけを出してすぐ終わる
#
# 見張る対象と検知の仕方:
#   U（HQ と同じ環境）  run.sh が置く終了コードのファイル。5 秒ごと
#   cleanup            登録簿から引いた pid のプロセスが消えたか。5 秒ごと
#   merge・close       gh で PR・issue の状態。GH_INTERVAL 秒（既定 60）ごと
# 別の環境で打つ U は見えないため見張らない。
#
# 出力（標準出力、1 行 1 件）:
#   EVENT=U3 EXIT=0 LOG=<ログのパス>
#   EVENT=merge-103 STATE=MERGED      MERGED のほか、マージせずに閉じたら CLOSED
#   EVENT=close-42 STATE=CLOSED
#   EVENT=cleanup-S9 SESSION=gone
#   EVENT=none                          見張る対象が無い
#   --status のときは次のどれか
#     WATCH=running PID=<pid>   見張りが動いている
#     WATCH=stopped             止まっていて、見張る対象がある。張り直す
#     WATCH=nothing             止まっていて、見張る対象が無い。張らない
# 起動した時点で既に片付いているものも、最初の 1 巡で知らせる。人が HQ より先に済ませても取りこぼさない。
# 見張る対象は 1 巡ごとに台帳から読み直す。走らせた後に足したお願いも、張り直さずに拾う。
#
# 1 つの台帳につき見張りは 1 本だけ動く。2 本目は WATCH=running を出してすぐ終わる。
# 見張りを走らせた Claude のセッションが消えたら、見張りも終わる。残ると次の HQ の見張りが立たない。
set -uo pipefail

# shellcheck source=_store.sh
. "$(dirname "$0")/_store.sh"

if [ "${1:-}" = "-l" ]; then
  [ -n "${2:-}" ] || { echo "watch.sh: -l には台帳名を渡してください" >&2; exit 2; }
  hq_ledger_name=$2
  shift 2
fi

ledger=$(hq_ledger_dir)
runs=$(hq_runs_dir)
mkdir -p "$ledger"
lock="$ledger/.watch.lock"

# 見張る対象が台帳に残っているか。別の環境で打つ U は見張れないため数えない。
has_targets() {
  local f
  for f in "$ledger"/*.md; do
    [ -f "$f" ] || continue
    [ "$(hq_field "$f" state)" = done ] && continue
    [ "$(hq_field "$f" kind)" = R ] && continue
    [ "$(hq_field "$f" place)" = host ] && continue
    return 0
  done
  return 1
}

exec 9>>"$lock"
if ! flock -n 9; then
  echo "WATCH=running PID=$(cat "$ledger/.watch.pid" 2>/dev/null)"
  exit 0
fi
if [ "${1:-}" = "--status" ]; then
  if has_targets; then echo "WATCH=stopped"; else echo "WATCH=nothing"; fi
  exit 0
fi
echo $$ > "$ledger/.watch.pid"

# 祖先をたどり、登録簿に載っている Claude のセッションを持ち主とする。見つからなければ持ち主を見ない。
# 登録簿には閉じたセッションの json も残るため、開始時刻まで合うものだけを持ち主と認める。
owner=""
p=$$
while [ "$p" -gt 1 ]; do
  if [ -f "$HQ_SESSIONS_DIR/$p.json" ] && [ "$(jq -r '.procStart // empty' "$HQ_SESSIONS_DIR/$p.json")" = "$(hq_proc_start "$p")" ]; then
    owner=$p
    break
  fi
  p=$(hq_proc_ppid "$p")
  [[ "$p" =~ ^[0-9]+$ ]] || break
done
owner_start=""
[ -n "$owner" ] && owner_start=$(hq_proc_start "$owner")

gh_interval=${GH_INTERVAL:-60}
last_gh=0

while true; do
  events=()
  watched=0
  now=$(date +%s)
  check_gh=0
  if [ $((now - last_gh)) -ge "$gh_interval" ]; then check_gh=1; last_gh=$now; fi

  for f in "$ledger"/*.md; do
    [ -f "$f" ] || continue
    [ "$(hq_field "$f" state)" = done ] && continue
    id=$(hq_field "$f" id)
    case "$(hq_field "$f" kind)" in
      U)
        [ "$(hq_field "$f" place)" = host ] && continue
        watched=1
        if [ -f "$runs/$id.exit" ]; then
          events+=("EVENT=$id EXIT=$(cat "$runs/$id.exit") LOG=$runs/$id.log")
        fi
        ;;
      cleanup)
        watched=1
        if [ "$(hq_proc_start "$(hq_field "$f" pid)")" != "$(hq_field "$f" procstart)" ]; then
          events+=("EVENT=$id SESSION=gone")
        fi
        ;;
      merge)
        watched=1
        if [ "$check_gh" = 1 ]; then
          state=$(gh pr view "$(hq_field "$f" target)" --json state -q .state 2>/dev/null) || state=""
          case "$state" in MERGED|CLOSED) events+=("EVENT=$id STATE=$state") ;; esac
        fi
        ;;
      close)
        watched=1
        if [ "$check_gh" = 1 ]; then
          state=$(gh issue view "$(hq_field "$f" target)" --json state -q .state 2>/dev/null) || state=""
          [ "$state" = CLOSED ] && events+=("EVENT=$id STATE=$state")
        fi
        ;;
    esac
  done

  if [ ${#events[@]} -gt 0 ]; then
    printf '%s\n' "${events[@]}"
    exit 0
  fi
  if [ "$watched" = 0 ]; then
    echo "EVENT=none"
    exit 0
  fi
  if [ -n "$owner" ] && [ "$(hq_proc_start "$owner")" != "$owner_start" ]; then
    exit 0
  fi
  sleep 5
done

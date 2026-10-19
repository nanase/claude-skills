# _store.sh — HQ のスクリプトが共有する保管先の解決。source して使う。
#
# 保管先はメインの作業ツリーの .claude/handoff である。カレントディレクトリのリポジトリから、
# git の共通ディレクトリをたどってメイン側を指す。worktree から呼ばれても同じ場所になる。
# worktree 側に別の台帳ができると、HQ がそれを見つけられない。
# スクリプトの置き場からはたどらない。プラグインとして入れると、置き場はプロジェクトの外になる。
#
# 環境変数 HQ_STORE で保管先を差し替えられる。本物の台帳を汚さずに試すためである。

hq_script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [ -z "${HQ_STORE:-}" ]; then
  hq_common_dir=$(git rev-parse --path-format=absolute --git-common-dir) || {
    echo "HQ の保管先が決まりません。プロジェクトのリポジトリの中で実行するか、HQ_STORE を渡してください" >&2
    exit 2
  }
  HQ_STORE="$(dirname "$hq_common_dir")/.claude/handoff"
fi

# 台帳を共有する HQ が複数いるときは、-l で台帳を分ける。通し番号は分けない。
# 番号が保管先全体で一意なら、人が「R3」と言ったときに指す先が 1 つに決まる。
hq_ledger_name=main

hq_ledger_dir() { printf '%s/ledger/%s' "$HQ_STORE" "$hq_ledger_name"; }
hq_runs_dir() { printf '%s/runs' "$HQ_STORE"; }

# セッションの登録簿。Claude Code がセッションごとに <pid>.json を置く。
HQ_SESSIONS_DIR="${HQ_SESSIONS_DIR:-$HOME/.claude/sessions}"

# /proc/<pid>/stat の n 番目の値を出す。pid が無ければ何も出さない。
# 2 番目のコマンド名は空白や括弧を含みうるため、最後の ")" より後ろを 3 番目から数える。
hq_proc_stat() {
  local stat n=$2
  stat=$(cat "/proc/$1/stat" 2>/dev/null) || return 0
  stat=${stat##*) }
  # shellcheck disable=SC2086
  set -- $stat
  printf '%s' "${!n-}"
}
hq_proc_start() { hq_proc_stat "$1" 20; }  # 22 番目: 開始時刻
hq_proc_ppid() { hq_proc_stat "$1" 2; }    # 4 番目: 親の pid

# 台帳の 1 件（frontmatter 付きの Markdown）から値を 1 つ読む。
hq_field() { awk -v k="$2: " 'NR==1 && $0=="---" {f=1; next} f && $0=="---" {exit} f && index($0, k)==1 {print substr($0, length(k)+1); exit}' "$1"; }

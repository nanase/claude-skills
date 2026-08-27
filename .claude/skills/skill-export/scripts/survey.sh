#!/usr/bin/env bash
# survey.sh — 派生リポジトリのスキルを棚卸しし、輸出の候補を洗い出す。
#
# 使い方: survey.sh [-b <ベースのスキル置き場>] <owner/repo>...
#   -b を省くと ./skills を、無ければカレントディレクトリをベースとする。
#   ベースの置き場は平坦（skills/<スキル>）でも入れ子（plugins/<名>/skills/<スキル>）でもよい。
#   各リポジトリを浅くクローンし、次を出す。
#     - 共通（差分なし / 差分あり）・新規・上流管理 の別
#     - 固有結合の疑い（置き場の外へ出るリンク、リポジトリ名・owner 名の出現）
#   クローンは消さない。出力されたパスへそのまま diff -ru を掛けられる。
#
# 依存: gh / git。
set -euo pipefail

USAGE="使い方: survey.sh [-b <ベースのスキル置き場>] <owner/repo>..."

BASE=""
while getopts ":b:" opt; do
  case "$opt" in
    b) BASE="$OPTARG" ;;
    *) echo "$USAGE" >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))

[ "$#" -ge 1 ] || { echo "$USAGE" >&2; exit 2; }

if [ -z "$BASE" ]; then
  if [ -d "./skills" ]; then BASE="./skills"; else BASE="."; fi
fi
[ -d "$BASE" ] || { echo "ベースのスキル置き場が見つかりません: $BASE" >&2; exit 2; }

WORK="$(mktemp -d)"
echo "ベース: $BASE"
echo "クローン先: $WORK"

# スキルの所在は SKILL.md の親ディレクトリで決まる。置き場の名前（skills / .claude/skills）は
# リポジトリごとに違うため、名前ではなく SKILL.md から辿る。
skill_dirs() {
  find "$1" -name SKILL.md -not -path '*/.git/*' 2>/dev/null \
    | while read -r f; do dirname "$f"; done \
    | sort
}

# ベース側の置き場も、リポジトリによって平坦だったり入れ子だったりする。比較先と同じく
# SKILL.md から辿って「スキル名|パス」の索引を作り、名前で引く。
BASE_INDEX="$(skill_dirs "$BASE" | while read -r d; do echo "$(basename "$d")|$d"; done)"

base_dir() {
  echo "$BASE_INDEX" | awk -F'[|]' -v n="$1" '$1==n {print $2; exit}'
}

DUP="$(echo "$BASE_INDEX" | cut -d'|' -f1 | sort | uniq -d)"
if [ -n "$DUP" ]; then
  echo "警告: ベースに同名のスキルが複数あります。最初の 1 つと比べます: $(echo $DUP)" >&2
fi

# スキル文書は <置き場>/<スキル>/FILE.md に置かれる。相対リンクの `../` 1 段は置き場を指すが、
# 2 段以上はその外＝リポジトリ本体を指す。結合している証拠として扱う。
ESCAPING_LINK='\]\((\.\./){2,}'

for REPO in "$@"; do
  NAME="${REPO##*/}"
  OWNER="${REPO%%/*}"
  DEST="$WORK/$NAME"

  echo
  echo "===== $REPO ====="
  gh repo clone "$REPO" "$DEST" -- --depth 1 --quiet >/dev/null 2>&1 || {
    echo "クローンに失敗しました。アクセス権と gh の認証を確認してください。" >&2
    continue
  }
  echo "clone: $DEST"

  same=""; differ=""; fresh=""; upstream=""
  while read -r d; do
    [ -n "$d" ] || continue
    s="$(basename "$d")"
    if grep -qE '^[[:space:]]*github-repo:' "$d/SKILL.md" 2>/dev/null; then
      upstream="$upstream $s"
    elif b="$(base_dir "$s")"; [ -n "$b" ]; then
      if diff -rq "$b" "$d" >/dev/null 2>&1; then same="$same $s"; else differ="$differ $s"; fi
    else
      fresh="$fresh $s"
    fi
  done <<EOF
$(skill_dirs "$DEST")
EOF

  echo "共通・差分なし:${same:- なし}"
  echo "共通・差分あり:${differ:- なし}"
  echo "新規:${fresh:- なし}"
  echo "上流管理:${upstream:- なし}"

  echo "-- 固有結合の疑い --"
  hit=0
  while read -r d; do
    [ -n "$d" ] || continue
    out="$(grep -rniE "$ESCAPING_LINK|$NAME|$OWNER" "$d" --include='*.md' --include='*.sh' --include='*.py' 2>/dev/null || true)"
    if [ -n "$out" ]; then
      echo "$out" | sed "s|^$WORK/||"
      hit=1
    fi
  done <<EOF
$(skill_dirs "$DEST")
EOF
  [ "$hit" -eq 1 ] || echo "検出なし"
done

echo
echo "差分は diff -ru <ベース側のスキルのパス> $WORK/<リポジトリ>/<置き場>/<スキル> で読む。"
echo "ベース側は平坦とは限らない。<ベース>/<スキル> と決め打ちしない。"

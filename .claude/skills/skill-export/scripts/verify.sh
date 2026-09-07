#!/usr/bin/env bash
# verify.sh — 輸出後のスキル置き場を検証する。落ちた項目を出し、1 つでもあれば終了 1。
#
# 使い方: verify.sh [-b <スキル置き場>] [<落としたはずの語>...]
#   -b を省くと ./skills を、無ければカレントディレクトリを見る。
#   語を渡すと、その残存を大文字小文字を無視して探す（固有名詞・ドメイン語彙の消し残し）。
#
#   見るのは次の 6 つ。
#     1. 落としたはずの語の残存
#     2. 置き場の外へ出る相対リンク（リポジトリ本体への結合）
#     3. 相対リンクの解決
#     4. ディレクトリ名と frontmatter の name の一致、description の有無
#     5. スクリプトの構文
#     6. 箇条書きの体裁（装飾の太字、末尾の「。」）
#
# 依存: bash と標準的な UNIX ツール（find・grep・sed・awk）。python3 があれば .py の
# コンパイルも見る。
set -euo pipefail

BASE=""
while getopts ":b:" opt; do
  case "$opt" in
    b) BASE="$OPTARG" ;;
    *) echo "使い方: verify.sh [-b <スキル置き場>] [<落としたはずの語>...]" >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))

if [ -z "$BASE" ]; then
  if [ -d "./skills" ]; then BASE="./skills"; else BASE="."; fi
fi
[ -d "$BASE" ] || { echo "スキル置き場が見つかりません: $BASE" >&2; exit 2; }

FAIL=0
ng() { echo "NG $*"; FAIL=1; }

md_files() { find "$BASE" -name '*.md' -not -path '*/.git/*' | sort; }

echo "検証対象: $BASE"

echo "== 1. 落としたはずの語の残存 =="
if [ "$#" -ge 1 ]; then
  PAT="$(printf '%s|' "$@")"; PAT="${PAT%|}"
  out="$(grep -rniE "$PAT" "$BASE" 2>/dev/null || true)"
  if [ -n "$out" ]; then echo "$out"; FAIL=1; else echo "残存なし"; fi
else
  echo "語の指定なし（省略）"
fi

echo "== 2. 置き場の外へ出る相対リンク =="
# スキル文書は <置き場>/<スキル>/FILE.md にある。`../` 1 段は置き場を指すが、2 段以上は
# その外＝リポジトリ本体を指し、輸出先で解決しない結合になる。
out="$(grep -rnE '\]\((\.\./){2,}' "$BASE" --include='*.md' 2>/dev/null || true)"
if [ -n "$out" ]; then echo "$out"; FAIL=1; else echo "検出なし"; fi

echo "== 3. 相対リンクの解決 =="
n=0
while read -r f; do
  d="$(dirname "$f")"
  while read -r link; do
    [ -n "$link" ] || continue
    [ -e "$d/$link" ] || ng "$f -> $link"
    n=$((n + 1))
  done <<EOF
$(grep -ohE '\]\([^)#][^)]*\)' "$f" 2>/dev/null | sed 's/^](\(.*\))$/\1/' | grep -v '^[a-z][a-z0-9+.-]*://' || true)
EOF
done <<EOF
$(md_files)
EOF
echo "$n 件を確認"

echo "== 4. frontmatter =="
while read -r f; do
  [ -n "$f" ] || continue
  d="$(basename "$(dirname "$f")")"
  name="$(grep -m1 '^name:' "$f" | sed 's/^name:[[:space:]]*//' || true)"
  [ "$d" = "$name" ] || ng "$f のディレクトリ名 '$d' と name '$name' が一致しません"
  grep -q '^description:' "$f" || ng "$f に description がありません"
done <<EOF
$(find "$BASE" -name SKILL.md -not -path '*/.git/*' | sort)
EOF
echo "確認完了"

echo "== 5. スクリプトの構文 =="
while read -r f; do
  [ -n "$f" ] || continue
  bash -n "$f" || ng "$f の構文エラー"
done <<EOF
$(find "$BASE" -name '*.sh' -not -path '*/.git/*')
EOF
if command -v python3 >/dev/null 2>&1; then
  while read -r f; do
    [ -n "$f" ] || continue
    python3 -m py_compile "$f" || ng "$f のコンパイルエラー"
  done <<EOF
$(find "$BASE" -name '*.py' -not -path '*/.git/*')
EOF
  find "$BASE" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
else
  echo "python3 が無いため .py は省略"
fi
echo "確認完了"

echo "== 6. 箇条書きの体裁 =="
# コードフェンスの中は、わざと崩した例や出力テンプレートが入るので見ない。
style_hit=0
while read -r f; do
  [ -n "$f" ] || continue
  out="$(awk '
    /^[[:space:]]*```/ { fence = !fence; next }
    fence { next }
    /^[[:space:]]*-[[:space:]]*\*\*/ { print FILENAME ":" FNR ": 装飾の太字 — " $0 }
    /^[[:space:]]*-[[:space:]].*。$/ { print FILENAME ":" FNR ": 末尾の「。」 — " $0 }
  ' "$f")"
  if [ -n "$out" ]; then echo "$out"; style_hit=1; FAIL=1; fi
done <<EOF
$(md_files)
EOF
if [ "$style_hit" -eq 0 ]; then echo "検出なし"; fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "全項目を通過した。"
else
  echo "落ちた項目がある。上の NG と検出行を直すこと。"
  exit 1
fi

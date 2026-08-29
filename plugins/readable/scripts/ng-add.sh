#!/usr/bin/env bash
# 使わないと決めた語を .claude/NG.md へ追記する。語の是非は readable-japanese が判断する。
# 入力は標準入力の TSV で、列は 語・言い換え・文脈 とする。言い換えと文脈は空でよい。
# 既出の語でも、言い換えが空のままなら後から言い換えだけを埋める。
set -euo pipefail

root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
target="$root/.claude/NG.md"

if [ ! -f "$target" ]; then
  mkdir -p "$(dirname "$target")"
  cat > "$target" <<'HEADER'
# NG 語彙

このプロジェクトで使わないと決めた語である。readable-japanese が語彙を見るときに併せて参照する。

追記は `/readable:ng` が行う。手で書いてもよい。

言い換えが空の行は、まだ代替語を決めていない。`/readable:ng <語>→<言い換え>` を後から打つか、まとめて仕分けするときに埋める。

| 語 | 言い換え | 文脈 | 記録日 |
| --- | --- | --- | --- |
HEADER
fi

today=$(date +%Y-%m-%d)
added=0
updated=0
skipped=0

# タブは IFS の空白文字で、read に任せると連続したタブが 1 つに畳まれる。
# 空の言い換えが消えて文脈が繰り上がるため、行を自分で切り分ける。
split_field() {
  local rest=$1
  if [ "${rest#*	}" = "$rest" ]; then
    printf '%s

' "$rest"
  else
    printf '%s
%s
' "${rest%%	*}" "${rest#*	}"
  fi
}

while IFS= read -r line || [ -n "${line:-}" ]; do
  line=$(printf '%s' "$line" | tr -d '')
  [ -z "$line" ] && continue

  word=${line%%	*}
  rest=${line#*	}
  [ "$rest" = "$line" ] && rest=""
  replacement=${rest%%	*}
  context=${rest#*	}
  [ "$context" = "$rest" ] && context=""

  word=$(printf '%s' "$word" | sed 's/^ *//; s/ *$//')
  [ -z "$word" ] && continue
  replacement=$(printf '%s' "$replacement" | tr -d '|' | sed 's/^ *//; s/ *$//')
  context=$(printf '%s' "$context" | tr -d '|' | sed 's/^ *//; s/ *$//')

  if grep -qF "| $word |" "$target"; then
    # 言い換えが空のまま記録されている語は、後から言い換えだけを埋められる。
    if [ -n "$replacement" ] && grep -qF "| $word |  |" "$target"; then
      sed -i "s#^| $word |  |#| $word | $replacement |#" "$target"
      printf '言い換えを追記: %s → %s
' "$word" "$replacement"
      updated=$((updated + 1))
    else
      printf '既出: %s
' "$word"
      skipped=$((skipped + 1))
    fi
    continue
  fi

  printf '| %s | %s | %s | %s |
' "$word" "$replacement" "$context" "$today" >> "$target"
  printf '追記: %s
' "$word"
  added=$((added + 1))
done

printf '%s へ %d 件追記、%d 件に言い換えを補い、%d 件は既出
' "${target#"$root/"}" "$added" "$updated" "$skipped"

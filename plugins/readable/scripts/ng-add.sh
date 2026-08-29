#!/usr/bin/env bash
# 使わないと決めた語を .claude/NG.md へ追記する。語の是非は readable-japanese が判断する。
# 入力は標準入力の TSV で、列は 語・言い換え・文脈 とする。言い換えと文脈は空でよい。
set -euo pipefail

root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
target="$root/.claude/NG.md"

if [ ! -f "$target" ]; then
  mkdir -p "$(dirname "$target")"
  cat > "$target" <<'HEADER'
# NG 語彙

このプロジェクトで使わないと決めた語である。readable-japanese が語彙を見るときに併せて参照する。

追記は `/readable:ng` が行う。手で書いてもよい。

言い換えが空の行は、まだ代替語を決めていない。まとめて仕分けするときに埋める。

| 語 | 言い換え | 文脈 | 記録日 |
| --- | --- | --- | --- |
HEADER
fi

today=$(date +%Y-%m-%d)
added=0
skipped=0

while IFS=$'\t' read -r word replacement context || [ -n "${word:-}" ]; do
  word=$(printf '%s' "${word:-}" | tr -d '\r' | sed 's/^ *//; s/ *$//')
  [ -z "$word" ] && continue

  if grep -qF "| $word |" "$target"; then
    printf '既出: %s\n' "$word"
    skipped=$((skipped + 1))
    continue
  fi

  replacement=$(printf '%s' "${replacement:-}" | tr -d '\r|' | sed 's/^ *//; s/ *$//')
  context=$(printf '%s' "${context:-}" | tr -d '\r|' | sed 's/^ *//; s/ *$//')

  printf '| %s | %s | %s | %s |\n' "$word" "$replacement" "$context" "$today" >> "$target"
  printf '追記: %s\n' "$word"
  added=$((added + 1))
done

printf '%s へ %d 件追記、%d 件は既出\n' "${target#"$root/"}" "$added" "$skipped"

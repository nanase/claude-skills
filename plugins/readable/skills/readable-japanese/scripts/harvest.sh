#!/usr/bin/env bash
# Markdown の変更履歴から語の置き換え候補を拾い、Markdown の表で出す。仕分けは人が行う。
# 引数で範囲を絞れる。例: harvest.sh -30 / harvest.sh v1.0..HEAD
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
python=$(command -v python3 || command -v python)

git log -p --no-color --no-renames --no-merges "$@" -- '*.md' | "$python" "$here/harvest.py"

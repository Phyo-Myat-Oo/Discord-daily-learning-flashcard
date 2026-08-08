#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
  echo "Refusing automated generation: the working tree is not clean." >&2
  exit 1
fi

git pull --ff-only
total_needed="$(python3 scripts/generate_prompt.py --count-only)"
if [[ "$total_needed" == "0" ]]; then
  echo "Every configured stream has reached its future-card target; nothing to do."
  exit 0
fi

echo "Generating $total_needed card(s) to restore all configured stream buffers."
while IFS= read -r stream; do
  needed="$(python3 scripts/generate_prompt.py --stream "$stream" --count-only)"
  if [[ "$needed" == "0" ]]; then
    continue
  fi
  echo "Generating $needed card(s) for stream: $stream"
  python3 scripts/generate_prompt.py --stream "$stream" | codex exec --ephemeral --sandbox workspace-write -C "$repo_dir" -
  python3 scripts/validate_cards.py
done < <(python3 -c 'from scripts.cardlib import load_channels; print("\n".join(load_channels()))')

# New card files and the topic index are the only permitted generation changes.
while IFS= read -r change; do
  [[ -z "$change" ]] && continue
  status="${change:0:2}"
  path="${change:3}"
  if [[ "$status" == "??" && "$path" == cards/* && "$path" != cards/imported/* && "$path" != "cards/schema.json" ]]; then
    continue
  fi
  if [[ "$path" == "state/topics.json" ]]; then
    continue
  fi
  echo "Refusing to commit out-of-scope Codex change: $change" >&2
  exit 1
done < <(git status --porcelain --untracked-files=all)

python3 scripts/validate_cards.py

if git diff --quiet && [[ -z "$(git status --short --untracked-files=normal)" ]]; then
  echo "Codex produced no changes." >&2
  exit 1
fi

git add cards state/topics.json
python3 scripts/validate_cards.py
git commit -m "chore(cards): replenish daily learning buffer"
git push

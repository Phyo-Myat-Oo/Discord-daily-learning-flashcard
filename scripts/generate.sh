#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

# A stalled Codex process must not keep the systemd service alive forever.
# Override this for unusually large batches, for example:
# CODEX_TIMEOUT_SECONDS=1800 ./scripts/generate.sh
codex_timeout_seconds="${CODEX_TIMEOUT_SECONDS:-900}"
if [[ ! "$codex_timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "CODEX_TIMEOUT_SECONDS must be a positive integer (received: $codex_timeout_seconds)." >&2
  exit 2
fi

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
  while true; do
    needed="$(python3 scripts/generate_prompt.py --stream "$stream" --count-only)"
    if [[ "$needed" == "0" ]]; then
      break
    fi
    batch_size=4
    if (( needed < batch_size )); then
      batch_size="$needed"
    fi
    echo "Generating $batch_size of $needed missing card(s) for stream: $stream"

    # Preserve both pipeline exit codes so timeout and prompt failures receive
    # useful diagnostics instead of being hidden by `set -e`.
    set +e
    python3 scripts/generate_prompt.py --stream "$stream" --limit "$batch_size" \
      | timeout --signal=TERM --kill-after=30s "${codex_timeout_seconds}s" \
          codex exec --ephemeral --sandbox workspace-write -C "$repo_dir" -
    pipeline_status=("${PIPESTATUS[@]}")
    set -e

    prompt_status="${pipeline_status[0]}"
    codex_status="${pipeline_status[1]}"
    if (( prompt_status != 0 )); then
      echo "Prompt generation failed for stream '$stream' (exit $prompt_status)." >&2
      exit "$prompt_status"
    fi
    if (( codex_status == 124 || codex_status == 137 )); then
      echo "Codex timed out after ${codex_timeout_seconds}s while generating stream '$stream'." >&2
      echo "No commit or push was attempted. Inspect the working tree before retrying." >&2
      exit 124
    fi
    if (( codex_status != 0 )); then
      echo "Codex failed for stream '$stream' (exit $codex_status). No commit or push was attempted." >&2
      exit "$codex_status"
    fi

    python3 scripts/validate_cards.py

    remaining="$(python3 scripts/generate_prompt.py --stream "$stream" --count-only)"
    if (( remaining >= needed )); then
      echo "Codex completed but made no scheduling progress for stream '$stream'." >&2
      echo "Missing cards before: $needed; missing cards after: $remaining." >&2
      echo "Stopping to prevent an infinite generation loop; no commit or push was attempted." >&2
      exit 1
    fi
    echo "Stream '$stream' progressed: $needed missing before, $remaining after."
  done
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

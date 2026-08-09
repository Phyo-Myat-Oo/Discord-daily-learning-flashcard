#!/usr/bin/env python3
"""Run a Codex quality review, then schedule only complete all-stream date rows."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cardlib import ROOT, all_cards, load_card, load_channels


def paths_below(targets: list[Path]) -> list[Path]:
    return sorted({path for target in targets for path in ([target] if target.is_file() else target.rglob("*.json")) if path.name != "schema.json"})


def validate(paths: list[Path] | None = None) -> bool:
    command = [sys.executable, str(ROOT / "scripts/validate_cards.py")]
    if paths:
        command.extend(map(str, paths))
    return subprocess.run(command).returncode == 0


def run_ai_review(paths: list[Path], timeout: int) -> bool:
    relative = [str(path.resolve().relative_to(ROOT)) for path in paths]
    prompt = f"""Read AGENTS.md and cards/schema.json. Perform a strict second-pass review of only these candidate cards:\n{json.dumps(relative, indent=2)}\n\nCheck technical accuracy, source fidelity, atomicity, English clarity, natural Burmese meaning, safety, duplicate concepts, useful depth, and answer correctness. Correct defects only inside these listed files. Do not inspect Git history or any deleted files. Do not schedule, approve, or change status. Run python scripts/validate_cards.py on these paths. If a claim cannot be supported, set that card's status to rejected. Finish promptly."""
    try:
        result = subprocess.run(["codex", "exec", "--ephemeral", "--sandbox", "workspace-write", "-C", str(ROOT), "-"], input=prompt, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"AI review timed out after {timeout}s; nothing will be scheduled.", file=sys.stderr)
        return False
    if result.returncode:
        print("AI review failed; nothing will be scheduled.", file=sys.stderr)
        return False
    return validate(paths)


def schedule_complete_rows(paths: list[Path], start: date) -> int:
    streams = list(load_channels())
    candidates: dict[str, list[tuple[Path, dict]]] = {stream: [] for stream in streams}
    for path in paths:
        card = load_card(path)
        if card.get("status") == "candidate" and card.get("stream") in candidates and not card.get("needs_review"):
            candidates[card["stream"]].append((path, card))
    for stream in streams:
        candidates[stream].sort(key=lambda item: (item[1].get("track_sequence", 10**9), item[1]["id"]))
    row_count = min((len(items) for items in candidates.values()), default=0)
    if row_count == 0:
        print("No complete all-stream rows are available; reviewed candidates remain unscheduled.", file=sys.stderr)
        return 0
    existing = list(all_cards())
    occupied = {(card.get("stream"), card.get("date")) for _, card in existing if card.get("date")}
    next_sequence = {stream: max((int(card.get("sequence", 0)) for _, card in existing if card.get("stream") == stream), default=0) + 1 for stream in streams}
    cursor = start
    scheduled = 0
    review_time = datetime.now(timezone.utc).isoformat()
    for row in range(row_count):
        while any((stream, cursor.isoformat()) in occupied for stream in streams):
            cursor += timedelta(days=1)
        for stream in streams:
            path, card = candidates[stream][row]
            card["date"] = cursor.isoformat()
            card["sequence"] = next_sequence[stream]
            card["status"] = "scheduled"
            card["ai_review"] = {"status": "passed", "reviewed_at": review_time, "reviewer": "codex"}
            path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            occupied.add((stream, cursor.isoformat()))
            next_sequence[stream] += 1
            scheduled += 1
        cursor += timedelta(days=1)
    return scheduled


def main() -> int:
    parser = argparse.ArgumentParser(description="AI-review candidate cards and schedule complete daily rows")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date.today() + timedelta(days=1))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--review-already-completed", action="store_true", help="use only when the current Codex session already performed the review")
    args = parser.parse_args()
    paths = paths_below(args.paths)
    if not paths:
        print("No cards found.", file=sys.stderr)
        return 2
    if not args.review_already_completed and not run_ai_review(paths, args.timeout):
        return 1
    if not validate(paths):
        return 1
    originals = {path: path.read_text(encoding="utf-8") for path in paths}
    scheduled = schedule_complete_rows(paths, args.start_date)
    if not scheduled:
        return 2
    if not validate():
        for path, original in originals.items():
            path.write_text(original, encoding="utf-8")
        print("Full validation failed after scheduling; candidate files were restored.", file=sys.stderr)
        return 1
    print(f"AI-reviewed and scheduled {scheduled} card(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

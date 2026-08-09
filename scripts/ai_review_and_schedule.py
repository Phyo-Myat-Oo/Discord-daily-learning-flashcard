#!/usr/bin/env python3
"""Run a Codex quality review, then schedule only complete all-stream date rows."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

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
    review_id = uuid4().hex
    prompt = f"""Read AGENTS.md, cards/schema.json, and state/terminology.json. Act as an independent teaching-quality reviewer for only these cards:\n{json.dumps(relative, indent=2)}\n\nFor each card verify: (1) exactly one observable learning objective, (2) prerequisites and unfamiliar terms are explained before use, (3) the explanation moves from concrete experience to cause and effect, (4) the example has an observable expected result, (5) what_to_notice interprets rather than repeats that result, (6) Burmese reads like an independent explanation by a patient technical instructor, (7) the visual materially clarifies the concept and stays within 48 characters per line, and (8) the recall answer follows directly from the lesson. Also check technical accuracy, source fidelity, safety, duplicate concepts, and Discord length. If comprehension fails, perform one focused rewrite and reassess once. If it still fails or a claim cannot be supported, set status to rejected. For every passing card, set ai_review to status `passed`, reviewer `codex-teaching-review`, a current UTC reviewed_at, and review_id `{review_id}`. Do not change dates, sequences, or a passing card's status. Run python scripts/validate_cards.py on these paths and finish promptly."""
    try:
        result = subprocess.run(["codex", "exec", "--ephemeral", "--sandbox", "workspace-write", "-C", str(ROOT), "-"], input=prompt, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"AI review timed out after {timeout}s; nothing will be scheduled.", file=sys.stderr)
        return False
    if result.returncode:
        print("AI review failed; nothing will be scheduled.", file=sys.stderr)
        return False
    unproven = []
    for path in paths:
        card = load_card(path)
        if card.get("status") != "rejected" and card.get("ai_review", {}).get("review_id") != review_id:
            unproven.append(str(path.relative_to(ROOT)))
    if unproven:
        print("AI review returned without proving review of: " + ", ".join(unproven), file=sys.stderr)
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
            review = card.get("ai_review", {})
            card["ai_review"] = {"status": "passed", "reviewed_at": review.get("reviewed_at", review_time), "reviewer": "codex-teaching-review", "review_id": review.get("review_id", "legacy-reviewed")}
            path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            occupied.add((stream, cursor.isoformat()))
            next_sequence[stream] += 1
            scheduled += 1
        cursor += timedelta(days=1)
    return scheduled


def stamp_reviewed(paths: list[Path]) -> int:
    review_time = datetime.now(timezone.utc).isoformat()
    reviewed = 0
    for path in paths:
        card = load_card(path)
        if card.get("status") == "rejected":
            continue
        card["ai_review"] = {"status": "passed", "reviewed_at": review_time, "reviewer": "codex-teaching-review", "review_id": "current-session-verified"}
        path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        reviewed += 1
    return reviewed


def main() -> int:
    parser = argparse.ArgumentParser(description="AI-review candidate cards and schedule complete daily rows")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date.today() + timedelta(days=1))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--review-already-completed", action="store_true", help="use only when the current Codex session already performed the review")
    parser.add_argument("--review-only", action="store_true", help="review and stamp existing cards without changing their schedule")
    args = parser.parse_args()
    paths = paths_below(args.paths)
    if not paths:
        print("No cards found.", file=sys.stderr)
        return 2
    if not args.review_already_completed and not run_ai_review(paths, args.timeout):
        return 1
    if not validate(paths):
        return 1
    if args.review_only:
        originals = {path: path.read_text(encoding="utf-8") for path in paths}
        reviewed = stamp_reviewed(paths)
        if not reviewed:
            print("No passing cards were available to stamp.", file=sys.stderr)
            return 2
        if not validate():
            for path, original in originals.items():
                path.write_text(original, encoding="utf-8")
            print("Full validation failed after review stamping; files were restored.", file=sys.stderr)
            return 1
        print(f"AI-reviewed {reviewed} existing card(s); schedules were unchanged.")
        return 0
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

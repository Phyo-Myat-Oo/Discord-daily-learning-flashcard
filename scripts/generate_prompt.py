#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from cardlib import ROOT, all_cards

ROTATION = {0: "linux", 1: "ai / machine learning", 2: "linux / networking", 3: "docker / DevOps / MLOps", 4: "python / git", 5: "AI engineering", 6: "review or a deeper practical concept"}


def missing_dates(target: int = 14, today: date | None = None) -> list[date]:
    today = today or date.today()
    occupied = {date.fromisoformat(c["date"]) for _, c in all_cards() if c.get("date") and date.fromisoformat(c["date"]) >= today and c.get("status") in {"approved", "scheduled"}}
    result: list[date] = []
    cursor = today
    while len(occupied | set(result)) < target:
        if cursor not in occupied: result.append(cursor)
        cursor += timedelta(days=1)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=14)
    parser.add_argument("--count-only", action="store_true")
    args = parser.parse_args()
    needed = missing_dates(args.target)
    if args.count_only:
        print(len(needed)); return 0
    template = (ROOT / "prompts/generate_cards.md").read_text(encoding="utf-8")
    topics = json.loads((ROOT / "state/topics.json").read_text(encoding="utf-8"))
    recent = sorted((c for _, c in all_cards() if c.get("date")), key=lambda c: c["date"], reverse=True)[:10]
    context = {
        "today": date.today().isoformat(),
        "missing_count": len(needed),
        "dates_and_rotation": [{"date": day.isoformat(), "suggested_category": ROTATION[day.weekday()]} for day in needed],
        "covered_topics": topics.get("covered", []),
        "recent_cards": [{key: c.get(key) for key in ("id", "date", "category", "topic", "title", "question")} for c in recent],
        "output_root": "cards/<category>/",
    }
    print(template + "\n## Dynamic context\n\n```json\n" + json.dumps(context, indent=2) + "\n```\n")
    return 0


if __name__ == "__main__": raise SystemExit(main())


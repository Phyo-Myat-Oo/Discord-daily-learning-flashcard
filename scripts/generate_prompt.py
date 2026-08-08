#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from cardlib import ROOT, all_cards, load_channels


def missing_slots(target_override: int | None = None, today: date | None = None, stream_filter: str | None = None) -> list[dict[str, str]]:
    today = today or date.today()
    channels = load_channels()
    cards = list(all_cards())
    result: list[dict[str, str]] = []
    for stream, config in channels.items():
        if stream_filter and stream != stream_filter:
            continue
        target = target_override or int(config.get("buffer_target", 14))
        occupied = {date.fromisoformat(c["date"]) for _, c in cards if c.get("stream") == stream and c.get("date") and date.fromisoformat(c["date"]) >= today and c.get("status") in {"approved", "scheduled"}}
        cursor = today
        planned: set[date] = set()
        categories = config["categories"]
        while len(occupied | planned) < target:
            if cursor not in occupied:
                planned.add(cursor)
                suggested = "review" if cursor.weekday() == 6 else categories[cursor.weekday() % len(categories)]
                result.append({"stream": stream, "date": cursor.isoformat(), "suggested_category": suggested})
            cursor += timedelta(days=1)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, help="override every stream's configured target")
    parser.add_argument("--stream", choices=load_channels().keys(), help="calculate or generate one stream only")
    parser.add_argument("--limit", type=int, help="limit this prompt to the first N missing slots")
    parser.add_argument("--count-only", action="store_true")
    args = parser.parse_args()
    needed = missing_slots(args.target, stream_filter=args.stream)
    if args.count_only:
        print(len(needed)); return 0
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be at least 1")
        needed = needed[:args.limit]
    template = (ROOT / "prompts/generate_cards.md").read_text(encoding="utf-8")
    topics = json.loads((ROOT / "state/topics.json").read_text(encoding="utf-8"))
    recent = sorted((c for _, c in all_cards() if c.get("date")), key=lambda c: c["date"], reverse=True)[:10]
    context = {
        "today": date.today().isoformat(),
        "missing_count": len(needed),
        "stream_date_slots": needed,
        "stream_configuration": load_channels(),
        "covered_topics": topics.get("covered", []),
        "recent_cards": [{key: c.get(key) for key in ("id", "stream", "date", "category", "topic", "title", "question")} for c in recent],
        "output_root": "cards/<category>/",
    }
    print(template + "\n## Dynamic context\n\n```json\n" + json.dumps(context, indent=2) + "\n```\n")
    return 0


if __name__ == "__main__": raise SystemExit(main())

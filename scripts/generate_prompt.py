#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from cardlib import ROOT, all_cards, load_channels, localized


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
        next_sequence = max((int(c.get("sequence", 0)) for _, c in cards if c.get("stream") == stream), default=0) + 1
        cursor = today
        planned: set[date] = set()
        categories = config["categories"]
        while len(occupied | planned) < target:
            if cursor not in occupied:
                planned.add(cursor)
                suggested = "review" if cursor.weekday() == 6 else categories[cursor.weekday() % len(categories)]
                progression = config.get("progression", {})
                if next_sequence <= int(progression.get("beginner_through", 5)):
                    stage = "beginner"
                elif next_sequence <= int(progression.get("intermediate_through", 20)):
                    stage = "intermediate"
                else:
                    stage = "advanced"
                result.append({"stream": stream, "date": cursor.isoformat(), "sequence": next_sequence, "required_difficulty": stage, "suggested_category": suggested})
                next_sequence += 1
            cursor += timedelta(days=1)
    return result


def build_prompt(slots: list[dict[str, str]], stream: str | None = None) -> str:
    """Build a compact, stable-prefix prompt for one generation job."""
    template = (ROOT / "prompts/generate_cards.md").read_text(encoding="utf-8")
    channels = load_channels()
    selected_streams = {name: config for name, config in channels.items() if not stream or name == stream}
    topics = json.loads((ROOT / "state/topics.json").read_text(encoding="utf-8"))
    covered = [
        {key: item.get(key) for key in ("stream", "sequence", "category", "topic", "id")}
        for item in topics.get("covered", [])
        if isinstance(item, dict)
    ]
    matching_cards = [
        card for _, card in all_cards()
        if not stream or card.get("stream") == stream
    ]
    recent = sorted(
        (card for card in matching_cards if card.get("date")),
        key=lambda card: card["date"],
        reverse=True,
    )[:8]
    context = {
        "today": date.today().isoformat(),
        "missing_count": len(slots),
        "stream_date_slots": slots,
        "stream_configuration": selected_streams,
        "terminology": json.loads((ROOT / "state/terminology.json").read_text(encoding="utf-8")),
        "covered_topics": covered,
        "recent_cards": [
            {
                **{key: card.get(key) for key in ("id", "stream", "date", "sequence", "category", "topic")},
                "title": localized(card, "en", "title"),
                "question": localized(card, "en", "question"),
            }
            for card in recent
        ],
    }
    return template + "\n## Dynamic context\n\n```json\n" + json.dumps(context, ensure_ascii=False, indent=2) + "\n```\n"


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
    print(build_prompt(needed, args.stream))
    return 0


if __name__ == "__main__": raise SystemExit(main())

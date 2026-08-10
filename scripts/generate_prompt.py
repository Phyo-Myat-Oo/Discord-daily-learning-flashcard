#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from cardlib import ROOT, all_cards, load_channels, localized

NEUROSCIENCE_PLAN = ROOT / "state/neuroscience_plan.json"
NEUROSCIENCE_CATALOG = ROOT / ".generated/neuroscience/catalog.json"


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
        if stream == "neuroscience":
            if not NEUROSCIENCE_PLAN.exists():
                raise ValueError("enabled neuroscience stream requires state/neuroscience_plan.json")
            plan = json.loads(NEUROSCIENCE_PLAN.read_text(encoding="utf-8"))
            if plan.get("status") != "active":
                raise ValueError("enabled neuroscience stream requires an active neuroscience plan")
            for assignment in plan.get("days", []):
                assignment_date = date.fromisoformat(assignment["date"])
                if assignment_date < today or assignment_date in occupied:
                    continue
                result.append({
                    "stream": stream,
                    "date": assignment["date"],
                    "sequence": assignment["course_day"],
                    "required_difficulty": assignment["difficulty"],
                    "suggested_category": "neuroscience",
                    "study_plan": {key: assignment[key] for key in (
                        "course_day", "course_week", "study_duration_minutes", "source_id",
                        "source_title", "source_locator", "source_url", "online_resource", "workload", "assessment", "tasks", "study_output",
                    ) if key in assignment},
                    "module": assignment["module"],
                    "day_type": assignment["day_type"],
                    "topic_focus": assignment["topic"],
                    "source_section_number": assignment["source_section_number"],
                    "source_section_numbers": assignment.get(
                        "source_section_numbers", [assignment["source_section_number"]]
                    ),
                })
                if len([item for item in result if item["stream"] == stream]) >= max(0, target - len(occupied)):
                    break
            continue
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


def neuroscience_source_material(slots: list[dict[str, object]]) -> list[dict[str, str]]:
    if not any(slot.get("stream") == "neuroscience" for slot in slots):
        return []
    if not NEUROSCIENCE_CATALOG.exists():
        raise ValueError("neuroscience source catalog is missing; rescan the local books")
    catalog = json.loads(NEUROSCIENCE_CATALOG.read_text(encoding="utf-8"))
    plan_state = json.loads(NEUROSCIENCE_PLAN.read_text(encoding="utf-8"))
    for source_id, expected in plan_state.get("sources", {}).items():
        actual = catalog.get("sources", {}).get(source_id)
        if not actual or actual.get("sha256") != expected.get("sha256"):
            raise ValueError(f"neuroscience source {source_id} changed; rescan and rebuild before generating")
    material: list[dict[str, str]] = []
    for slot in slots:
        if slot.get("stream") != "neuroscience":
            continue
        plan = slot["study_plan"]
        entry = catalog["sources"].get(plan["source_id"])
        if not entry:
            raise ValueError(f"neuroscience source {plan['source_id']} is unavailable")
        cached = json.loads((ROOT / entry["cache_file"]).read_text(encoding="utf-8"))
        section_numbers = slot.get("source_section_numbers", [slot["source_section_number"]])
        sections = [
            item for number in section_numbers
            for item in cached["sections"] if item["number"] == int(number)
        ]
        if len(sections) != len(section_numbers):
            raise ValueError(f"source sections {section_numbers} are unavailable for {plan['source_id']}")
        text = "\n".join(str(section["text"]) for section in sections)
        page_match = re.search(r"PDF pages (\d+)[–-](\d+)", str(plan["source_locator"]))
        if page_match:
            first, last = map(int, page_match.groups())
            pieces = re.split(r"(?=\[Page \d+\])", text)
            selected = []
            for piece in pieces:
                marker = re.match(r"\[Page (\d+)\]", piece)
                if marker and first <= int(marker.group(1)) <= last:
                    selected.append(piece)
            excerpt = "\n".join(selected) or text[:12000]
        else:
            excerpt = text[:12000]
        material.append({
            "date": str(slot["date"]),
            "source_title": str(plan["source_title"]),
            "source_locator": str(plan["source_locator"]),
            "excerpt": excerpt[:16000],
        })
    return material


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
        "source_material": neuroscience_source_material(slots),
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

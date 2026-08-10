#!/usr/bin/env python3
"""Synchronize generated neuroscience cards with their locked plan assignments."""
from __future__ import annotations

import json
import sys

from cardlib import ROOT, all_cards

PLAN_PATH = ROOT / "state/neuroscience_plan.json"
PLAN_FIELDS = (
    "course_day", "course_week", "study_duration_minutes", "source_id", "source_title",
    "source_locator", "source_url", "online_resource", "workload", "assessment", "tasks", "study_output",
)


def main() -> int:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if plan.get("status") != "active":
        print("Neuroscience plan must be active before cards can be synchronized.", file=sys.stderr)
        return 2
    assignments = {int(day["course_day"]): day for day in plan["days"]}
    updated = 0
    for path, card in all_cards():
        if card.get("stream") != "neuroscience":
            continue
        sequence = int(card.get("sequence", 0))
        assignment = assignments.get(sequence)
        if not assignment or card.get("date") != assignment.get("date"):
            print(f"Cannot synchronize {path}: sequence/date does not match the active plan.", file=sys.stderr)
            return 2
        card["study_plan"] = {field: assignment[field] for field in PLAN_FIELDS if assignment.get(field) is not None}
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updated += 1
    print(f"Synchronized {updated} neuroscience card(s) with the active plan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

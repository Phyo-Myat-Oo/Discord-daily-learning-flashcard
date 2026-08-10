#!/usr/bin/env python3
"""Show neuroscience source, syllabus, activation, and upcoming-day status."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from cardlib import ROOT, load_channels

PLAN_PATH = ROOT / "state/neuroscience_plan.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--next", type=int, default=7, help="number of study days to show")
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    args = parser.parse_args()
    if args.next < 1 or args.next > 30:
        parser.error("--next must be between 1 and 30")
    if not args.plan.exists():
        print("No neuroscience plan exists. Scan sources, then build the plan.", file=sys.stderr)
        return 2
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    configured = load_channels(include_disabled=True).get("neuroscience", {})
    print(f"Plan: {plan.get('course_title')} ({len(plan.get('days', []))} days)")
    print(f"Status: {plan.get('status')} • channel enabled: {configured.get('enabled', False)}")
    print(f"Start date: {plan.get('start_date') or 'not assigned'}")
    today = date.today().isoformat()
    upcoming = [day for day in plan.get("days", []) if not day.get("date") or day["date"] >= today]
    for day in upcoming[:args.next]:
        when = day.get("date") or f"Day {day['course_day']}"
        print(f"  {when} • Week {day['course_week']} • {day['day_type']}: {day['topic']}")
        print(f"    {day['source_locator']}")
        if day.get("workload"):
            load = day["workload"]
            print(f"    workload: {load['estimated_reading_minutes']} min source study • {load['density']} density • {load['word_count']} words")
        if day.get("online_resource"):
            print(f"    optional: {day['online_resource']['title']} — {day['online_resource']['url']}")
        if day.get("assessment"):
            refs = ", ".join(f"Day {item['course_day']}" for item in day["assessment"]["items"])
            print(f"    self-assessment: {refs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

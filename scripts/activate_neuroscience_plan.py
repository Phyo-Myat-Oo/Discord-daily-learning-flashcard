#!/usr/bin/env python3
"""Date and enable a complete source-verified neuroscience study plan."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from cardlib import ROOT
from neuroscience_sources import CATALOG_PATH

PLAN_PATH = ROOT / "state/neuroscience_plan.json"
CHANNELS_PATH = ROOT / "config/channels.json"


def next_monday(today: date) -> date:
    delta = (7 - today.weekday()) % 7
    return today + timedelta(days=delta or 7)


def prepare_activation(plan: dict, catalog: dict, channels: dict, start_date: date, allow_midweek: bool = False) -> tuple[dict, dict]:
    if start_date.weekday() != 0 and not allow_midweek:
        raise ValueError("the neuroscience course must start on a Monday to preserve the 5+1+1 rhythm")
    if plan.get("status") == "active":
        raise ValueError("the neuroscience plan is already active; refusing to replace its dates")
    if len(plan.get("days", [])) != 182:
        raise ValueError("the plan must contain exactly 182 days")
    if catalog.get("missing_required"):
        raise ValueError("required source files are missing; rescan before activation")
    for source_id, expected in plan.get("sources", {}).items():
        actual = catalog.get("sources", {}).get(source_id)
        if not actual or actual.get("sha256") != expected.get("sha256"):
            raise ValueError(f"source {source_id} changed or is unavailable; rebuild the plan")
    for offset, day in enumerate(plan["days"]):
        day["date"] = (start_date + timedelta(days=offset)).isoformat()
    plan["status"] = "active"
    plan["start_date"] = start_date.isoformat()
    channels["streams"]["neuroscience"]["enabled"] = True
    return plan, channels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat, default=next_monday(date.today()))
    parser.add_argument("--allow-midweek", action="store_true", help="start Course Day 1 on a non-Monday and shift the complete 5+1+1 cycle")
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args()
    if args.start_date < date.today():
        print("The neuroscience start date cannot be in the past.", file=sys.stderr)
        return 2
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        channels = json.loads(CHANNELS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot activate neuroscience plan: {exc}", file=sys.stderr)
        return 2
    try:
        plan, channels = prepare_activation(plan, catalog, channels, args.start_date, args.allow_midweek)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    plan_tmp = args.plan.with_suffix(".json.tmp")
    channels_tmp = CHANNELS_PATH.with_suffix(".json.tmp")
    plan_tmp.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    channels_tmp.write_text(json.dumps(channels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(plan_tmp, args.plan)
    os.replace(channels_tmp, CHANNELS_PATH)
    print(f"Activated 182 study days from {args.start_date} through {plan['days'][-1]['date']}.")
    print("Next: configure DISCORD_WEBHOOK_NEUROSCIENCE, run generation_runner.py, validate, then commit everything together.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

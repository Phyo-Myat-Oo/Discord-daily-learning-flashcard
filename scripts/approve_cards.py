#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from cardlib import ROOT, all_cards, load_card

parser = argparse.ArgumentParser(description="Approve candidate cards, optionally assigning spaced future dates")
parser.add_argument("path", type=Path)
parser.add_argument("--schedule", action="store_true")
parser.add_argument("--start-date", type=date.fromisoformat, default=date.today())
parser.add_argument("--spacing-days", type=int, default=3)
args = parser.parse_args()
paths = [args.path] if args.path.is_file() else sorted(args.path.rglob("*.json"))
occupied = {c["date"] for _, c in all_cards() if c.get("date")}
cursor = args.start_date
changed = 0
for path in paths:
    card = load_card(path)
    if card.get("status") != "candidate": continue
    card["status"] = "approved"
    if args.schedule:
        while cursor.isoformat() in occupied: cursor += timedelta(days=1)
        card["date"] = cursor.isoformat(); card["status"] = "scheduled"; occupied.add(card["date"])
        cursor += timedelta(days=max(1, args.spacing_days))
    path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    changed += 1
result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_cards.py")])
if result.returncode:
    print("Validation failed. Fix or revert the edited cards before committing.", file=sys.stderr); raise SystemExit(1)
print(f"Approved {changed} card(s)." + (" Dates were spaced across unused slots." if args.schedule else " Add dates before daily delivery."))


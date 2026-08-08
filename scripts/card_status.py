#!/usr/bin/env python3
from collections import Counter
from datetime import date
from cardlib import all_cards

today = date.today()
cards = list(all_cards())
future = [(p, c) for p, c in cards if c.get("date") and date.fromisoformat(c["date"]) >= today and c.get("status") in {"approved", "scheduled"}]
statuses = Counter(c.get("status", "missing") for _, c in cards)
print(f"Today: {today.isoformat()}")
print(f"Sendable future buffer: {len(future)} (target 14, minimum 7)")
print("Statuses: " + ", ".join(f"{key}={value}" for key, value in sorted(statuses.items())))
if future:
    print(f"Coverage: {min(c['date'] for _, c in future)} through {max(c['date'] for _, c in future)}")
if len(future) < 7:
    print("WARNING: future-card buffer is below 7.")


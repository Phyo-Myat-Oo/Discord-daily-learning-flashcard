#!/usr/bin/env python3
from collections import Counter
from datetime import date
from cardlib import all_cards, load_channels

today = date.today()
cards = list(all_cards())
statuses = Counter(c.get("status", "missing") for _, c in cards)
print(f"Today: {today.isoformat()}")
print("Statuses: " + ", ".join(f"{key}={value}" for key, value in sorted(statuses.items())))
for stream, config in load_channels().items():
    future = [(p, c) for p, c in cards if c.get("stream") == stream and c.get("date") and date.fromisoformat(c["date"]) >= today and c.get("status") in {"approved", "scheduled"}]
    target = int(config.get("buffer_target", 14))
    coverage = f"{min(c['date'] for _, c in future)} through {max(c['date'] for _, c in future)}" if future else "none"
    warning = "  WARNING: below 7" if len(future) < 7 else ""
    print(f"{stream:8} {len(future):2}/{target} cards  coverage: {coverage}{warning}")

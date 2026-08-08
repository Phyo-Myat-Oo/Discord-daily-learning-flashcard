#!/usr/bin/env python3
from cardlib import all_cards

candidates = [(p, c) for p, c in all_cards() if c.get("status") == "candidate"]
if not candidates:
    print("No candidate cards.")
for path, card in candidates:
    print(f"\n[{card.get('priority', 'normal').upper()}] {card['id']} — {card['title']}")
    print(f"  {card['question']}\n  → {card['answer']}\n  {path}")


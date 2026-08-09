#!/usr/bin/env python3
from cardlib import all_cards, localized

candidates = [(p, c) for p, c in all_cards() if c.get("status") == "candidate"]
if not candidates:
    print("No candidate cards.")
for path, card in candidates:
    print(f"\n[{card.get('priority', 'normal').upper()}] {card['id']} — {localized(card, 'en', 'title')}")
    print(f"  EN: {localized(card, 'en', 'question')}\n  → {localized(card, 'en', 'answer')}")
    if card.get("language") == "bilingual":
        print(f"  MY: {localized(card, 'my', 'question')}\n  → {localized(card, 'my', 'answer')}")
    print(f"  {path}")

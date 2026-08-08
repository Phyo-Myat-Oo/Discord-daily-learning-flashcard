#!/usr/bin/env python3
import json
from cardlib import ROOT

items = json.loads((ROOT / "state/imports.json").read_text(encoding="utf-8")).get("imports", [])
print(f"Processed source revisions: {len(items)}")
for item in items:
    print(f"{item['processed_at']}  {item['source_file']}  {item['cards_generated']} cards  {item['sha256'][:12]}")


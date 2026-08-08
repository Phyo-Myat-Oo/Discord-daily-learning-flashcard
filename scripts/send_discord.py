#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date

from cardlib import find_card, format_discord


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or send a dated flashcard to Discord")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", help="date in YYYY-MM-DD form")
    group.add_argument("--today", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    day = date.today().isoformat() if args.today else args.date
    try:
        match = find_card(day)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Card lookup failed: {exc}", file=sys.stderr); return 1
    if not match:
        print(f"No approved or scheduled card exists for {day}.", file=sys.stderr); return 2
    message = format_discord(match[1])
    if len(message) > 1900:
        print(f"Refusing to send {len(message)}-character message; run validation.", file=sys.stderr); return 1
    if args.dry_run:
        print(message); return 0
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("DISCORD_WEBHOOK_URL is not set.", file=sys.stderr); return 1
    request = urllib.request.Request(webhook, data=json.dumps({"content": message, "allowed_mentions": {"parse": []}}).encode(), headers={"Content-Type": "application/json", "User-Agent": "daily-learning/1.0"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status not in {200, 204}:
                print(f"Discord returned HTTP {response.status}.", file=sys.stderr); return 1
    except urllib.error.HTTPError as exc:
        body = exc.read(500).decode(errors="replace")
        print(f"Discord returned HTTP {exc.code}: {body}", file=sys.stderr); return 1
    except urllib.error.URLError as exc:
        print(f"Discord request failed: {exc.reason}", file=sys.stderr); return 1
    print(f"Sent card for {day}: {match[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


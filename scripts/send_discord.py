#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date

from cardlib import build_discord_payload, find_card, format_discord, load_channels


def prepare(day: str, stream_names: list[str], dry_run: bool) -> tuple[list[tuple[str, str, dict, str]], list[str]]:
    """Preflight every stream before any network request is made."""
    channels = load_channels()
    prepared: list[tuple[str, str, dict, str]] = []
    errors: list[str] = []
    for stream in stream_names:
        if stream not in channels:
            errors.append(f"Unknown stream: {stream}")
            continue
        try:
            match = find_card(day, stream)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{stream}: card lookup failed: {exc}")
            continue
        if not match:
            errors.append(f"{stream}: no approved or scheduled card exists for {day}")
            continue
        payload = build_discord_payload(match[1])
        preview = format_discord(match[1])
        env_name = channels[stream].get("webhook_env", "")
        webhook = "dry-run" if dry_run else os.environ.get(env_name, "")
        if not webhook:
            errors.append(f"{stream}: required environment variable {env_name} is not set")
            continue
        prepared.append((stream, webhook, payload, preview))
    return prepared, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or send a dated flashcard to Discord")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", help="date in YYYY-MM-DD form")
    group.add_argument("--today", action="store_true")
    stream_group = parser.add_mutually_exclusive_group(required=True)
    stream_group.add_argument("--stream", help="one stream key from config/channels.json")
    stream_group.add_argument("--all", action="store_true", help="process every configured stream")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    day = date.today().isoformat() if args.today else args.date
    channels = load_channels()
    stream_names = list(channels) if args.all else [args.stream]
    prepared, errors = prepare(day, stream_names, args.dry_run)
    if errors:
        for error in errors: print(error, file=sys.stderr)
        return 2
    if args.dry_run:
        for index, (stream, _, _, preview) in enumerate(prepared):
            if index: print("\n" + "=" * 72 + "\n")
            print(f"[{stream} → {channels[stream]['display_name']}]\n{preview}")
        return 0
    for stream, webhook, payload, _ in prepared:
        request = urllib.request.Request(webhook, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "User-Agent": "daily-learning/1.0"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status not in {200, 204}:
                    print(f"{stream}: Discord returned HTTP {response.status}.", file=sys.stderr); return 1
        except urllib.error.HTTPError as exc:
            body = exc.read(500).decode(errors="replace")
            print(f"{stream}: Discord returned HTTP {exc.code}: {body}", file=sys.stderr); return 1
        except urllib.error.URLError as exc:
            print(f"{stream}: Discord request failed: {exc.reason}", file=sys.stderr); return 1
        print(f"Sent {stream} card for {day}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

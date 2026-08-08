#!/usr/bin/env python3
"""Validate every flashcard. Exits non-zero on errors."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from cardlib import REQUIRED, VALID_CATEGORIES, VALID_DIFFICULTIES, VALID_PRIORITIES, VALID_STATUSES, card_paths, format_discord, load_card, normalized_words, parse_date

SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?:sk|rk)-(?:live|test|proj)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)(?:api[_-]?key|password|secret|token)\s*[=:]\s*['\"]?[A-Za-z0-9_./+-]{12,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
DANGEROUS = re.compile(r"(?:^|\s)(rm\s+(?:-[^\s]*r[^\s]*f|-[^\s]*f[^\s]*r)|dd\s+if=|mkfs(?:\.|\s)|chmod\s+-R|chown\s+-R|docker\s+system\s+prune|git\s+reset\s+--hard)(?:\s|$)", re.I)
WARN_WORDS = re.compile(r"danger|destructive|irreversible|delete|overwrite|data loss|backup|caution", re.I)


def validate(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    ids: dict[str, Path] = {}
    dates: dict[str, Path] = {}
    topics: defaultdict[tuple[str, str], list[tuple[Path, dict]]] = defaultdict(list)
    for path in paths:
        try:
            card = load_card(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{path}: malformed JSON: {exc}")
            continue
        missing = REQUIRED - card.keys()
        if missing:
            errors.append(f"{path}: missing fields: {', '.join(sorted(missing))}")
        for key, value in card.items():
            if value is None or value == "" or value == []:
                errors.append(f"{path}: empty field: {key}")
        if card.get("category") not in VALID_CATEGORIES:
            errors.append(f"{path}: invalid category: {card.get('category')}")
        if card.get("difficulty") not in VALID_DIFFICULTIES:
            errors.append(f"{path}: invalid difficulty: {card.get('difficulty')}")
        if card.get("status") not in VALID_STATUSES:
            errors.append(f"{path}: invalid status: {card.get('status')}")
        if card.get("priority", "normal") not in VALID_PRIORITIES:
            errors.append(f"{path}: invalid priority: {card.get('priority')}")
        if card.get("status") == "scheduled" and not card.get("date"):
            errors.append(f"{path}: scheduled card requires date")
        if card.get("date"):
            try:
                parse_date(card["date"])
            except (TypeError, ValueError):
                errors.append(f"{path}: invalid ISO date: {card.get('date')}")
            if card["date"] in dates:
                errors.append(f"{path}: duplicate date also used by {dates[card['date']]}")
            dates[card["date"]] = path
        card_id = card.get("id")
        if card_id in ids:
            errors.append(f"{path}: duplicate id also used by {ids[card_id]}")
        elif card_id:
            ids[card_id] = path
        if not isinstance(card.get("tags"), list) or not all(isinstance(tag, str) and tag.strip() for tag in card.get("tags", [])):
            errors.append(f"{path}: tags must be a non-empty string list")
        if card.get("generated_from_source"):
            for field in ("source_type", "source_file"):
                if not card.get(field): errors.append(f"{path}: source card missing {field}")
        if card.get("category") == "review":
            items = card.get("review_items")
            if not isinstance(items, list) or len(items) < 2 or any(not isinstance(item, dict) or not item.get("question") or not item.get("answer") for item in (items or [])):
                errors.append(f"{path}: review cards require at least two non-empty review_items")
        raw = json.dumps(card, ensure_ascii=False)
        if any(pattern.search(raw) for pattern in SECRET_PATTERNS):
            errors.append(f"{path}: possible secret or credential detected")
        command_text = " ".join(str(card.get(k, "")) for k in ("command", "example", "answer"))
        if DANGEROUS.search(command_text) and not WARN_WORDS.search(f"{card.get('explanation', '')} {card.get('use_case', '')}"):
            errors.append(f"{path}: dangerous command lacks an explicit safety warning")
        if REQUIRED <= card.keys():
            message = format_discord(card)
            if len(message) > 1900:
                errors.append(f"{path}: Discord message is {len(message)} characters (limit: 1900)")
        key = (str(card.get("category", "")), str(card.get("topic", "")).lower().strip())
        topics[key].append((path, card))
    for (category, topic), items in topics.items():
        if topic and len(items) > 1:
            for index, (path_a, card_a) in enumerate(items):
                for path_b, card_b in items[index + 1:]:
                    a = normalized_words(f"{card_a.get('title','')} {card_a.get('question','')}")
                    b = normalized_words(f"{card_b.get('title','')} {card_b.get('question','')}")
                    similarity = len(a & b) / max(1, len(a | b))
                    if similarity >= .6:
                        errors.append(f"{path_b}: suspicious duplicate topic '{category}/{topic}' ({similarity:.0%}) with {path_a}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path, help="specific card files/directories (default: all cards)")
    args = parser.parse_args()
    paths = card_paths() if not args.paths else sorted({p for arg in args.paths for p in ([arg] if arg.is_file() else arg.rglob("*.json")) if p.name != "schema.json"})
    errors = validate(paths)
    if errors:
        print("Validation failed:", file=sys.stderr)
        for error in errors: print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"Validated {len(paths)} card(s) successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate every flashcard. Exits non-zero on errors."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from cardlib import BASE_REQUIRED, LEGACY_REQUIRED, RICH_REQUIRED, VALID_CATEGORIES, VALID_DIFFICULTIES, VALID_PRIORITIES, VALID_STATUSES, build_discord_payload, card_paths, is_bilingual, load_card, load_channels, localized, normalized_words, parse_date

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
    dates: dict[tuple[str, str], Path] = {}
    sequences: dict[tuple[str, int], Path] = {}
    topics: defaultdict[tuple[str, str], list[tuple[Path, dict]]] = defaultdict(list)
    try:
        streams = load_channels()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"config/channels.json: {exc}"]
    for stream_name, config in streams.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]+", stream_name):
            errors.append(f"config/channels.json: invalid stream key: {stream_name}")
        if not isinstance(config.get("display_name"), str) or not config["display_name"].strip():
            errors.append(f"config/channels.json: {stream_name} needs display_name")
        if not isinstance(config.get("categories"), list) or not config["categories"] or any(category not in VALID_CATEGORIES - {"review"} for category in config.get("categories", [])):
            errors.append(f"config/channels.json: {stream_name} has invalid categories")
        if not re.fullmatch(r"DISCORD_WEBHOOK_[A-Z0-9_]+", str(config.get("webhook_env", ""))):
            errors.append(f"config/channels.json: {stream_name} has invalid webhook_env")
        if not isinstance(config.get("buffer_target"), int) or not 1 <= config["buffer_target"] <= 60:
            errors.append(f"config/channels.json: {stream_name} buffer_target must be 1..60")
        progression = config.get("progression", {})
        beginner_through = progression.get("beginner_through")
        intermediate_through = progression.get("intermediate_through")
        if not isinstance(beginner_through, int) or not isinstance(intermediate_through, int) or not 1 <= beginner_through < intermediate_through:
            errors.append(f"config/channels.json: {stream_name} has invalid progression thresholds")
    for path in paths:
        try:
            card = load_card(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{path}: malformed JSON: {exc}")
            continue
        required = BASE_REQUIRED | ({"content"} if card.get("language") == "bilingual" else LEGACY_REQUIRED)
        missing = required - card.keys()
        if missing:
            errors.append(f"{path}: missing fields: {', '.join(sorted(missing))}")
        for key, value in card.items():
            if value is None or value == "" or value == []:
                errors.append(f"{path}: empty field: {key}")
        if card.get("category") not in VALID_CATEGORIES:
            errors.append(f"{path}: invalid category: {card.get('category')}")
        if card.get("language") not in {"my", "bilingual"}:
            errors.append(f"{path}: language must be 'my' or 'bilingual'")
        if is_bilingual(card):
            content = card.get("content", {})
            for language in ("en", "my"):
                block = content.get(language)
                if not isinstance(block, dict):
                    errors.append(f"{path}: content.{language} must be an object")
                    continue
                absent = RICH_REQUIRED - block.keys()
                if absent:
                    errors.append(f"{path}: content.{language} missing fields: {', '.join(sorted(absent))}")
                for field, value in block.items():
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"{path}: content.{language}.{field} must be non-empty text")
                if len(str(block.get("explanation", ""))) < (180 if language == "en" else 120):
                    errors.append(f"{path}: content.{language}.explanation is too short for a rich card")
                instructional = " ".join(str(block.get(name, "")) for name in ("summary", "explanation", "how_it_works", "use_case", "common_mistake", "practical_tip"))
                if len(instructional) < (550 if language == "en" else 400):
                    errors.append(f"{path}: content.{language} needs more instructional detail")
            my_text = " ".join(str(value) for value in content.get("my", {}).values()) if isinstance(content.get("my"), dict) else ""
            if not re.search(r"[က-႟]", my_text):
                errors.append(f"{path}: Burmese content contains no Myanmar script")
        stream = card.get("stream")
        if stream not in streams:
            errors.append(f"{path}: unknown stream: {stream}")
        elif card.get("category") not in streams[stream].get("categories", []) and card.get("category") != "review":
            errors.append(f"{path}: category {card.get('category')} is not allowed in stream {stream}")
        if card.get("difficulty") not in VALID_DIFFICULTIES:
            errors.append(f"{path}: invalid difficulty: {card.get('difficulty')}")
        if card.get("status") not in VALID_STATUSES:
            errors.append(f"{path}: invalid status: {card.get('status')}")
        if card.get("priority", "normal") not in VALID_PRIORITIES:
            errors.append(f"{path}: invalid priority: {card.get('priority')}")
        if card.get("status") == "scheduled" and not card.get("date"):
            errors.append(f"{path}: scheduled card requires date")
        if card.get("status") in {"approved", "scheduled"} and card.get("date") and not isinstance(card.get("sequence"), int):
            errors.append(f"{path}: dated sendable card requires an integer sequence")
        if isinstance(card.get("sequence"), int):
            sequence_key = (str(stream), card["sequence"])
            if sequence_key in sequences:
                errors.append(f"{path}: duplicate sequence in stream {stream}, also used by {sequences[sequence_key]}")
            sequences[sequence_key] = path
            if stream in streams:
                progression = streams[stream]["progression"]
                progression_number = card.get("track_sequence") if isinstance(card.get("track_sequence"), int) else card["sequence"]
                beginner_through = 5 if isinstance(card.get("track_sequence"), int) else progression["beginner_through"]
                intermediate_through = 20 if isinstance(card.get("track_sequence"), int) else progression["intermediate_through"]
                expected = "beginner" if progression_number <= beginner_through else "intermediate" if progression_number <= intermediate_through else "advanced"
                if card.get("difficulty") != expected:
                    errors.append(f"{path}: progression position {progression_number} in stream {stream} requires difficulty {expected}")
        if card.get("date"):
            try:
                parse_date(card["date"])
            except (TypeError, ValueError):
                errors.append(f"{path}: invalid ISO date: {card.get('date')}")
            date_key = (str(stream), card["date"])
            if date_key in dates:
                errors.append(f"{path}: duplicate date in stream {stream}, also used by {dates[date_key]}")
            dates[date_key] = path
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
        command_text = " ".join([str(card.get(k, "")) for k in ("command", "example", "answer")]+ [localized(card, lang, "answer") for lang in ("en", "my")])
        safety_text = " ".join([str(card.get("explanation", "")), str(card.get("use_case", ""))] + [localized(card, lang, field) for lang in ("en", "my") for field in ("explanation", "use_case", "common_mistake", "practical_tip")])
        if DANGEROUS.search(command_text) and not WARN_WORDS.search(safety_text):
            errors.append(f"{path}: dangerous command lacks an explicit safety warning")
        if not missing:
            payload = build_discord_payload(card)
            if len(payload.get("content", "")) > 1900:
                errors.append(f"{path}: Discord content exceeds safe 1900-character limit")
            embeds = payload.get("embeds", [])
            embed_total = 0
            for index, embed in enumerate(embeds, 1):
                if len(embed.get("title", "")) > 256:
                    errors.append(f"{path}: Discord embed {index} title exceeds 256 characters")
                if len(embed.get("description", "")) > 4096:
                    errors.append(f"{path}: Discord embed {index} description exceeds 4096 characters")
                embed_total += len(embed.get("title", "")) + len(embed.get("description", "")) + len(embed.get("footer", {}).get("text", ""))
            if embed_total > 6000:
                errors.append(f"{path}: Discord embeds contain {embed_total} characters (limit: 6000)")
        key = (str(card.get("category", "")), str(card.get("topic", "")).lower().strip())
        topics[key].append((path, card))
    for (category, topic), items in topics.items():
        if topic and len(items) > 1:
            for index, (path_a, card_a) in enumerate(items):
                for path_b, card_b in items[index + 1:]:
                    a = normalized_words(f"{localized(card_a, 'en', 'title')} {localized(card_a, 'en', 'question')}")
                    b = normalized_words(f"{localized(card_b, 'en', 'title')} {localized(card_b, 'en', 'question')}")
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

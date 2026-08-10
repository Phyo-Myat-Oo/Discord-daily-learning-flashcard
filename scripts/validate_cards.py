#!/usr/bin/env python3
"""Validate every flashcard. Exits non-zero on errors."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from cardlib import BASE_REQUIRED, LEGACY_REQUIRED, RICH_REQUIRED, VALID_CATEGORIES, VALID_DIFFICULTIES, VALID_PRIORITIES, VALID_STATUSES, build_discord_payload, card_paths, is_bilingual, is_rich, load_card, load_channels, localized, normalized_words, parse_date

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
        streams = load_channels(include_disabled=True)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"config/channels.json: {exc}"]
    resource_path = Path(__file__).resolve().parents[1] / "config/neuroscience_online_resources.json"
    try:
        resource_catalog = json.loads(resource_path.read_text(encoding="utf-8"))
        resources = resource_catalog.get("resources", {})
        week_resources = resource_catalog.get("week_resources", {})
        if set(week_resources) != {str(week) for week in range(1, 27)}:
            errors.append(f"{resource_path}: must map every Week 1..26 exactly once")
        for week, resource_id in week_resources.items():
            resource = resources.get(resource_id)
            if not isinstance(resource, dict) or not str(resource.get("url", "")).startswith("https://"):
                errors.append(f"{resource_path}: Week {week} has an invalid or non-HTTPS resource")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{resource_path}: malformed resource catalog: {exc}")
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
        if not isinstance(config.get("enabled", True), bool):
            errors.append(f"config/channels.json: {stream_name} enabled must be boolean")
    for path in paths:
        try:
            card = load_card(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{path}: malformed JSON: {exc}")
            continue
        required = BASE_REQUIRED | ({"content"} if card.get("language") in {"en", "bilingual"} else LEGACY_REQUIRED)
        missing = required - card.keys()
        renderable = not missing
        if missing:
            errors.append(f"{path}: missing fields: {', '.join(sorted(missing))}")
        for key, value in card.items():
            if value is None or value == "" or value == []:
                errors.append(f"{path}: empty field: {key}")
        if card.get("category") not in VALID_CATEGORIES:
            errors.append(f"{path}: invalid category: {card.get('category')}")
        if card.get("language") not in {"my", "en", "bilingual"}:
            errors.append(f"{path}: language must be 'my', 'en', or 'bilingual'")
        if is_rich(card):
            content = card.get("content", {})
            languages = ("en", "my") if is_bilingual(card) else ("en",)
            for language in languages:
                block = content.get(language)
                if not isinstance(block, dict):
                    errors.append(f"{path}: content.{language} must be an object")
                    continue
                absent = RICH_REQUIRED - block.keys()
                if absent:
                    errors.append(f"{path}: content.{language} missing fields: {', '.join(sorted(absent))}")
                    renderable = False
                for field, value in block.items():
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"{path}: content.{language}.{field} must be non-empty text")
                limits = {
                    "learning_objective": (30, 220),
                    "simple_explanation": ((140, 650) if language == "en" else (120, 750)),
                    "how_it_works": ((220, 850) if language == "en" else (180, 950)),
                    "use_case": ((100, 500) if language == "en" else (90, 600)),
                    "expected_result": (50, 450),
                    "what_to_notice": (60, 450),
                }
                for field, (minimum, maximum) in limits.items():
                    size = len(str(block.get(field, "")))
                    if not minimum <= size <= maximum:
                        errors.append(f"{path}: content.{language}.{field} must contain {minimum}..{maximum} characters")
                visual = str(block.get("visual", ""))
                if visual and (len(visual) < 20 or len(visual) > 500 or visual.count("\n") > 8):
                    errors.append(f"{path}: content.{language}.visual must be a useful diagram of 20..500 characters and at most 9 lines")
                if any(len(line) > 48 for line in visual.splitlines()):
                    errors.append(f"{path}: content.{language}.visual has a line wider than 48 characters (unsafe for Discord mobile)")
                instructional = " ".join(str(block.get(name, "")) for name in ("simple_explanation", "how_it_works", "use_case", "expected_result", "what_to_notice", "common_mistake", "practical_tip"))
                if len(instructional) < (900 if language == "en" else 750):
                    errors.append(f"{path}: content.{language} needs more instructional detail")
                prose_fields = ("simple_explanation", "how_it_works", "use_case", "expected_result", "what_to_notice")
                for index, field_a in enumerate(prose_fields):
                    words_a = normalized_words(str(block.get(field_a, "")))
                    for field_b in prose_fields[index + 1:]:
                        words_b = normalized_words(str(block.get(field_b, "")))
                        similarity = len(words_a & words_b) / max(1, min(len(words_a), len(words_b)))
                        if len(words_a) >= 8 and len(words_b) >= 8 and similarity >= .8:
                            errors.append(f"{path}: content.{language}.{field_a} and {field_b} repeat too much ({similarity:.0%})")
            if is_bilingual(card):
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
        study_plan = card.get("study_plan")
        if card.get("stream") == "neuroscience" and not isinstance(study_plan, dict):
            errors.append(f"{path}: neuroscience cards require study_plan")
        if isinstance(study_plan, dict):
            required_plan = {"course_day", "course_week", "study_duration_minutes", "source_id", "source_title", "source_locator", "tasks", "study_output"}
            absent = required_plan - study_plan.keys()
            if absent:
                errors.append(f"{path}: study_plan missing fields: {', '.join(sorted(absent))}")
            if study_plan.get("study_duration_minutes") != 60:
                errors.append(f"{path}: study_plan duration must be exactly 60 minutes")
            tasks = study_plan.get("tasks")
            if not isinstance(tasks, list) or not tasks:
                errors.append(f"{path}: study_plan tasks must be a non-empty array")
            else:
                minutes = 0
                for index, task in enumerate(tasks, 1):
                    if not isinstance(task, dict) or not {"minutes", "activity", "en"} <= task.keys():
                        errors.append(f"{path}: study_plan task {index} is incomplete")
                        continue
                    if not isinstance(task["minutes"], int) or task["minutes"] < 1:
                        errors.append(f"{path}: study_plan task {index} has invalid minutes")
                    else:
                        minutes += task["minutes"]
                    required_task_text = ("activity", "en", "my") if is_bilingual(card) else ("activity", "en")
                    if any(not isinstance(task.get(field), str) or not task[field].strip() for field in required_task_text):
                        errors.append(f"{path}: study_plan task {index} has missing instructions")
                if minutes != 60:
                    errors.append(f"{path}: study_plan task minutes total {minutes}, expected 60")
            output = study_plan.get("study_output")
            output_languages = ("en", "my") if is_bilingual(card) else ("en",)
            if not isinstance(output, dict) or any(not isinstance(output.get(language), str) or not output[language].strip() for language in output_languages):
                errors.append(f"{path}: study_plan study_output is incomplete")
            resource = study_plan.get("online_resource")
            if resource is not None and (not isinstance(resource, dict) or not all(isinstance(resource.get(key), str) and resource[key].strip() for key in ("title", "url")) or not str(resource.get("url", "")).startswith("https://")):
                errors.append(f"{path}: study_plan online_resource requires a title and HTTPS URL")
            workload = study_plan.get("workload")
            if workload is not None:
                required_workload = {"estimated_reading_minutes", "raw_text_minutes", "density", "word_count", "equation_lines", "figure_table_refs", "code_lines"}
                if not isinstance(workload, dict) or not required_workload <= workload.keys():
                    errors.append(f"{path}: study_plan workload metadata is incomplete")
                elif not 18 <= workload.get("estimated_reading_minutes", 0) <= 30 or workload.get("density") not in {"low", "medium", "high"}:
                    errors.append(f"{path}: study_plan workload is outside the adaptive reading policy")
                source_task = next((task for task in tasks or [] if isinstance(task, dict) and task.get("activity") == "Source study"), None)
                if source_task and source_task.get("minutes") != workload.get("estimated_reading_minutes"):
                    errors.append(f"{path}: source-study minutes do not match workload estimate")
            assessment = study_plan.get("assessment")
            if assessment is not None:
                blueprint = assessment.get("items") if isinstance(assessment, dict) else None
                if not isinstance(blueprint, list) or len(blueprint) != 5 or len({item.get("course_day") for item in blueprint if isinstance(item, dict)}) != 5:
                    errors.append(f"{path}: weekly assessment requires five distinct blueprint items")
                review_items = card.get("review_items")
                if not isinstance(review_items, list) or len(review_items) != 5:
                    errors.append(f"{path}: weekly assessment card requires exactly five review_items")
            if not isinstance(study_plan.get("source_locator"), str) or not study_plan.get("source_locator", "").strip():
                errors.append(f"{path}: study_plan requires a reliable source locator")
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
        if renderable:
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
                if len(embed.get("description", "")) > 2700:
                    errors.append(f"{path}: Discord embed {index} description exceeds the teaching budget of 2700 characters")
                embed_total += len(embed.get("title", "")) + len(embed.get("description", "")) + len(embed.get("footer", {}).get("text", ""))
            if embed_total > 5800:
                errors.append(f"{path}: Discord embeds contain {embed_total} characters (safe teaching limit: 5800)")
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

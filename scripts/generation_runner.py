#!/usr/bin/env python3
"""Generate curriculum cards concurrently without letting Codex edit the repo."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cardlib import ROOT, card_paths, load_channels
from generate_prompt import build_prompt, missing_slots
from validate_cards import validate


@dataclass(frozen=True)
class GenerationJob:
    name: str
    stream: str
    slots: tuple[dict[str, Any], ...]
    attempt: int = 0


@dataclass
class JobResult:
    job: GenerationJob
    cards: list[dict[str, Any]] | None
    elapsed: float
    error: str | None = None
    cached: bool = False


def positive_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer (received: {raw})") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer (received: {raw})")
    return value


def build_jobs(slots: list[dict[str, Any]], batch_size: int, attempt: int = 0) -> list[GenerationJob]:
    """Group slots by stream while retaining the configured stream order."""
    streams: dict[str, list[dict[str, Any]]] = {}
    for slot in slots:
        streams.setdefault(str(slot["stream"]), []).append(slot)
    jobs: list[GenerationJob] = []
    for stream, stream_slots in streams.items():
        for offset in range(0, len(stream_slots), batch_size):
            batch = tuple(stream_slots[offset:offset + batch_size])
            first = batch[0]["date"]
            last = batch[-1]["date"]
            suffix = f"-retry{attempt}" if attempt else ""
            jobs.append(GenerationJob(f"{stream}-{first}-{last}{suffix}", stream, batch, attempt))
    return jobs


def nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def output_schema(card_count: int, stream: str | None = None) -> dict[str, Any]:
    """Build a strict structured-output schema for curriculum cards."""
    rich_fields = {
        "title": {"type": "string"},
        "learning_objective": {"type": "string", "minLength": 30, "maxLength": 220},
        "simple_explanation": {"type": "string"},
        "how_it_works": {"type": "string"},
        "visual": {"type": "string"},
        "use_case": {"type": "string"},
        "expected_result": {"type": "string"},
        "what_to_notice": {"type": "string"},
        "common_mistake": {"type": "string"},
        "practical_tip": {"type": "string"},
        "question": {"type": "string"},
        "answer": {"type": "string"},
    }
    rich_language = {
        "type": "object",
        "properties": rich_fields,
        "required": list(rich_fields),
        "additionalProperties": False,
    }
    flag_fields = {
        "flag": {"type": "string"},
        "meaning": nullable({"type": "string"}),
        "en": nullable({"type": "string"}),
        "my": nullable({"type": "string"}),
    }
    review_fields = {"question": {"type": "string"}, "answer": {"type": "string"}}
    exercise_fields = {"instruction": {"type": "string"}, "output": {"type": "string"}}
    english_only = stream == "neuroscience"
    task_fields = {
        "minutes": {"type": "integer", "minimum": 1},
        "activity": {"type": "string"},
        "en": {"type": "string"},
    }
    if not english_only:
        task_fields["my"] = {"type": "string"}
    output_fields = {"en": {"type": "string"}}
    if not english_only:
        output_fields["my"] = {"type": "string"}
    online_fields = {"title": {"type": "string"}, "url": {"type": "string"}, "note": {"type": "string"}}
    workload_fields = {
        "estimated_reading_minutes": {"type": "integer", "minimum": 18, "maximum": 30},
        "raw_text_minutes": {"type": "number", "minimum": 0},
        "density": {"type": "string", "enum": ["low", "medium", "high"]},
        "word_count": {"type": "integer", "minimum": 0},
        "equation_lines": {"type": "integer", "minimum": 0},
        "figure_table_refs": {"type": "integer", "minimum": 0},
        "code_lines": {"type": "integer", "minimum": 0},
    }
    assessment_item_fields = {"course_day": {"type": "integer"}, "topic": {"type": "string"}, "module": {"type": "string"}, "review_age_days": {"type": "integer"}}
    assessment_fields = {
        "mode": {"type": "string", "const": "self-check"},
        "score_max": {"type": "integer", "const": 5},
        "items": {"type": "array", "minItems": 5, "maxItems": 5, "items": {"type": "object", "properties": assessment_item_fields, "required": list(assessment_item_fields), "additionalProperties": False}},
        "rubric": {"type": "string"},
    }
    study_fields = {
        "course_day": {"type": "integer", "minimum": 1, "maximum": 182},
        "course_week": {"type": "integer", "minimum": 1, "maximum": 26},
        "study_duration_minutes": {"type": "integer", "const": 60},
        "source_id": {"type": "string"},
        "source_title": {"type": "string"},
        "source_locator": {"type": "string"},
        "source_url": {"type": "string"},
        "online_resource": nullable({"type": "object", "properties": online_fields, "required": list(online_fields), "additionalProperties": False}),
        "workload": nullable({"type": "object", "properties": workload_fields, "required": list(workload_fields), "additionalProperties": False}),
        "assessment": nullable({"type": "object", "properties": assessment_fields, "required": list(assessment_fields), "additionalProperties": False}),
        "tasks": {
            "type": "array",
            "items": {"type": "object", "properties": task_fields, "required": list(task_fields), "additionalProperties": False},
        },
        "study_output": {"type": "object", "properties": output_fields, "required": list(output_fields), "additionalProperties": False},
    }
    card_fields: dict[str, Any] = {
        "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]+$"},
        "stream": {"type": "string"},
        "language": {"type": "string", "const": "en" if english_only else "bilingual"},
        "sequence": {"type": "integer", "minimum": 1},
        "date": {"type": "string"},
        "category": {"type": "string"},
        "topic": {"type": "string"},
        "difficulty": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
        "command": nullable({"type": "string"}),
        "flags": nullable({
            "type": "array",
            "items": {
                "type": "object",
                "properties": flag_fields,
                "required": list(flag_fields),
                "additionalProperties": False,
            },
        }),
        "example": {"type": "string"},
        "content": {
            "type": "object",
            "properties": ({"en": rich_language} if english_only else {"en": rich_language, "my": rich_language}),
            "required": (["en"] if english_only else ["en", "my"]),
            "additionalProperties": False,
        },
        "review_items": nullable({
            "type": "array",
            "items": {
                "type": "object",
                "properties": review_fields,
                "required": list(review_fields),
                "additionalProperties": False,
            },
        }),
        "active_exercise": nullable({"type": "object", "properties": exercise_fields, "required": list(exercise_fields), "additionalProperties": False}),
        "study_plan": nullable({
            "type": "object",
            "properties": study_fields,
            "required": list(study_fields),
            "additionalProperties": False,
        }),
        "tags": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "status": {"type": "string", "const": "approved"},
    }
    item_schema = {
        "type": "object",
        "properties": card_fields,
        "required": list(card_fields),
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "cards": {
                "type": "array",
                "minItems": card_count,
                "maxItems": card_count,
                "items": item_schema,
            }
        },
        "required": ["cards"],
        "additionalProperties": False,
    }


def strip_nullable_fields(card: dict[str, Any]) -> dict[str, Any]:
    """Remove structured-output null placeholders before project validation."""
    for field in ("command", "flags", "review_items", "active_exercise", "study_plan"):
        if card.get(field) is None:
            card.pop(field, None)
    for flag in card.get("flags", []):
        if isinstance(flag, dict):
            for field in tuple(flag):
                if flag[field] is None:
                    flag.pop(field)
    plan = card.get("study_plan")
    if isinstance(plan, dict) and plan.get("online_resource") is None:
        plan.pop("online_resource", None)
    if isinstance(plan, dict):
        for field in ("workload", "assessment"):
            if plan.get(field) is None:
                plan.pop(field, None)
    return card


def validate_job_cards(
    cards: Any,
    job: GenerationJob,
    channels: dict[str, dict[str, Any]],
) -> list[str]:
    """Check the fields that tie generated output to its assigned slots."""
    errors: list[str] = []
    if not isinstance(cards, list):
        return ["output.cards must be an array"]
    if len(cards) != len(job.slots):
        return [f"expected {len(job.slots)} cards, received {len(cards)}"]
    expected = {(slot["stream"], slot["date"], slot["sequence"]): slot for slot in job.slots}
    seen: set[tuple[Any, Any, Any]] = set()
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            errors.append(f"card {index + 1} is not an object")
            continue
        key = (card.get("stream"), card.get("date"), card.get("sequence"))
        if key not in expected:
            errors.append(f"card {index + 1} does not match an assigned stream/date/sequence slot")
            continue
        if key in seen:
            errors.append(f"card {index + 1} repeats assigned slot {key}")
        seen.add(key)
        slot = expected[key]
        if card.get("difficulty") != slot["required_difficulty"]:
            errors.append(f"card {index + 1} must use difficulty {slot['required_difficulty']}")
        if card.get("status") != "approved":
            errors.append(f"card {index + 1} must use approved status")
        category = card.get("category")
        allowed = set(channels[job.stream]["categories"]) | {"review"}
        if category not in allowed:
            errors.append(f"card {index + 1} category {category!r} is not allowed for {job.stream}")
    missing = set(expected) - seen
    if missing:
        errors.append(f"missing assigned slots: {sorted(missing)}")
    return errors


def load_output(path: Path, job: GenerationJob, channels: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"could not read structured output: {exc}"
    cards = value.get("cards") if isinstance(value, dict) else None
    if isinstance(cards, list):
        cards = [strip_nullable_fields(card) if isinstance(card, dict) else card for card in cards]
    errors = validate_job_cards(cards, job, channels)
    if errors:
        return None, "; ".join(errors)
    return cards, None


def validate_job_content(job_dir: Path, cards: list[dict[str, Any]]) -> str | None:
    """Run the complete project validator before accepting or caching a job."""
    validation_dir = job_dir / "validation"
    if validation_dir.exists():
        shutil.rmtree(validation_dir)
    paths: list[Path] = []
    for index, card in enumerate(cards, 1):
        category = str(card.get("category", "unknown"))
        card_id = str(card.get("id", f"card-{index}"))
        path = validation_dir / category / f"{card_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    generated_keys = {(card.get("stream"), card.get("date")) for card in cards}
    generated_streams = {card.get("stream") for card in cards}
    existing = []
    for path in card_paths():
        existing_card = json.loads(path.read_text(encoding="utf-8"))
        if existing_card.get("stream") not in generated_streams and (existing_card.get("stream"), existing_card.get("date")) not in generated_keys:
            existing.append(path)
    errors = validate(existing + paths)
    if errors:
        return "project validation failed: " + " | ".join(errors)
    return None


def terminate_process(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_job(
    job: GenerationJob,
    root: Path,
    run_dir: Path,
    timeout_seconds: int,
    channels: dict[str, dict[str, Any]],
    codex_command: str,
) -> JobResult:
    started = time.monotonic()
    job_dir = run_dir / "jobs" / job.name
    job_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_dir / "output.json"
    log_path = job_dir / "codex.log"
    prompt_path = job_dir / "prompt.txt"
    schema_path = job_dir / "output-schema.json"

    if output_path.exists():
        cards, error = load_output(output_path, job, channels)
        if cards is not None and not (error := validate_job_content(job_dir, cards)):
            return JobResult(job, cards, time.monotonic() - started, cached=True)
        output_path.unlink(missing_ok=True)

    prompt = build_prompt(list(job.slots), job.stream)
    prompt_path.write_text(prompt, encoding="utf-8")
    schema_path.write_text(
        json.dumps(output_schema(len(job.slots), job.stream), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    command = [
        codex_command,
        "exec",
        "--ephemeral",
        "--sandbox", "read-only",
        "-C", str(root),
        "--output-schema", str(schema_path),
        "--output-last-message", str(output_path),
        "-",
    ]
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=root,
            )
            try:
                process.communicate(prompt, timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                terminate_process(process)
                return JobResult(job, None, time.monotonic() - started, f"timed out after {timeout_seconds}s")
    except OSError as exc:
        return JobResult(job, None, time.monotonic() - started, f"could not start Codex: {exc}")
    if process.returncode != 0:
        return JobResult(job, None, time.monotonic() - started, f"Codex exited with status {process.returncode}; see {log_path}")
    cards, error = load_output(output_path, job, channels)
    if cards is not None and error is None:
        error = validate_job_content(job_dir, cards)
        if error:
            cards = None
    return JobResult(job, cards, time.monotonic() - started, error)


def run_job_wave(
    jobs: list[GenerationJob],
    root: Path,
    run_dir: Path,
    concurrency: int,
    timeout_seconds: int,
    channels: dict[str, dict[str, Any]],
    codex_command: str,
    heartbeat_seconds: int,
) -> list[JobResult]:
    results: list[JobResult] = []
    print(f"Starting {len(jobs)} job(s) with concurrency {min(concurrency, len(jobs))}.", flush=True)
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="card-generation") as executor:
        pending: dict[Future[JobResult], GenerationJob] = {
            executor.submit(run_job, job, root, run_dir, timeout_seconds, channels, codex_command): job
            for job in jobs
        }
        wave_started = time.monotonic()
        while pending:
            completed, _ = wait(pending, timeout=heartbeat_seconds, return_when=FIRST_COMPLETED)
            if not completed:
                active = ", ".join(job.name for job in pending.values())
                print(f"Still generating after {time.monotonic() - wave_started:.0f}s: {active}", flush=True)
                continue
            for future in completed:
                job = pending.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # Keep one worker failure from hiding other results.
                    result = JobResult(job, None, time.monotonic() - wave_started, f"unexpected worker error: {exc}")
                results.append(result)
                state = "cached" if result.cached else "completed" if not result.error else "failed"
                detail = f": {result.error}" if result.error else ""
                print(f"[{state}] {job.name} in {result.elapsed:.1f}s{detail}", flush=True)
    return results


def run_identifier(root: Path, slots: list[dict[str, Any]], batch_size: int) -> str:
    material = {
        "slots": slots,
        "batch_size": batch_size,
        "prompt": (root / "prompts/generate_cards.md").read_text(encoding="utf-8"),
        "schema": json.loads((root / "cards/schema.json").read_text(encoding="utf-8")),
        "channels": json.loads((root / "config/channels.json").read_text(encoding="utf-8")),
        "terminology": json.loads((root / "state/terminology.json").read_text(encoding="utf-8")),
        "topics": json.loads((root / "state/topics.json").read_text(encoding="utf-8")),
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def stage_and_validate(root: Path, run_dir: Path, cards: list[dict[str, Any]], replace_keys: set[tuple[str, str]] | None = None) -> list[Path]:
    stage_root = run_dir / "staged-cards"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    staged: list[Path] = []
    for card in cards:
        card_id = card.get("id")
        category = card.get("category")
        if not isinstance(card_id, str) or not isinstance(category, str):
            raise ValueError("generated cards require string id and category fields")
        destination = root / "cards" / category / f"{card_id}.json"
        if destination.exists() and (card.get("stream"), card.get("date")) not in (replace_keys or set()):
            raise ValueError(f"refusing to overwrite existing card: {destination.relative_to(root)}")
        path = stage_root / category / f"{card_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staged.append(path)
    existing = []
    for path in card_paths():
        card = json.loads(path.read_text(encoding="utf-8"))
        if (card.get("stream"), card.get("date")) not in (replace_keys or set()):
            existing.append(path)
    errors = validate(existing + staged)
    if errors:
        raise ValueError("staged card validation failed:\n  - " + "\n  - ".join(errors))
    return staged


def install_cards(root: Path, staged: list[Path], run_dir: Path, replace_keys: set[tuple[str, str]] | None = None) -> None:
    stage_root = run_dir / "staged-cards"
    installed_cards: list[dict[str, Any]] = []
    if replace_keys:
        for path in card_paths():
            card = json.loads(path.read_text(encoding="utf-8"))
            if (card.get("stream"), card.get("date")) in replace_keys:
                path.unlink()
    for source in staged:
        relative = source.relative_to(stage_root)
        destination = root / "cards" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".json.tmp")
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
        installed_cards.append(json.loads(source.read_text(encoding="utf-8")))

    topics_path = root / "state/topics.json"
    topics = json.loads(topics_path.read_text(encoding="utf-8"))
    covered = topics.setdefault("covered", [])
    if replace_keys:
        covered[:] = [item for item in covered if not isinstance(item, dict) or (item.get("stream"), item.get("date")) not in replace_keys]
    known_ids = {item.get("id") for item in covered if isinstance(item, dict)}
    for card in installed_cards:
        if card["id"] in known_ids:
            continue
        covered.append({
            "stream": card["stream"],
            "sequence": card["sequence"],
            "date": card["date"],
            "category": card["category"],
            "topic": card["topic"],
            "id": card["id"],
        })
    temporary_topics = topics_path.with_suffix(".json.tmp")
    temporary_topics.write_text(json.dumps(topics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_topics, topics_path)


def print_plan(slots: list[dict[str, Any]], jobs: list[GenerationJob], concurrency: int) -> None:
    print(f"Missing cards: {len(slots)}")
    print(f"Planned jobs: {len(jobs)} (maximum concurrency: {concurrency})")
    for job in jobs:
        assignments = ", ".join(f"{slot['date']}#{slot['sequence']}" for slot in job.slots)
        print(f"  {job.name}: {assignments}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", help="show planned jobs without calling Codex")
    parser.add_argument("--count-only", action="store_true", help="print only the missing-card count")
    parser.add_argument("--target", type=int, help="override every stream's configured buffer target")
    parser.add_argument("--stream", choices=load_channels().keys(), help="generate only one configured stream")
    parser.add_argument("--regenerate", action="store_true", help="replace the selected stream's current future buffer after all replacements validate")
    args = parser.parse_args()
    try:
        concurrency = positive_env("CODEX_GENERATION_CONCURRENCY", 2)
        batch_size = positive_env("CODEX_GENERATION_BATCH_SIZE", 2)
        timeout_seconds = positive_env("CODEX_TIMEOUT_SECONDS", 900)
        retries = positive_env("CODEX_GENERATION_RETRIES", 1)
        heartbeat_seconds = positive_env("CODEX_HEARTBEAT_SECONDS", 30)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.regenerate and not args.stream:
        parser.error("--regenerate requires --stream")
    slots = missing_slots(args.target, stream_filter=args.stream, replace_existing_stream=args.stream if args.regenerate else None)
    if args.count_only:
        print(len(slots))
        return 0
    jobs = build_jobs(slots, batch_size)
    if args.plan:
        print_plan(slots, jobs, concurrency)
        return 0
    if not slots:
        print("Every configured stream has reached its future-card target; nothing to do.")
        return 0

    channels = load_channels()
    run_id = run_identifier(ROOT, slots, batch_size)
    run_dir = ROOT / ".generated" / "curriculum" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    codex_command = os.environ.get("CODEX_COMMAND", "codex")
    all_results = run_job_wave(
        jobs, ROOT, run_dir, concurrency, timeout_seconds, channels,
        codex_command, heartbeat_seconds,
    )
    successful: list[dict[str, Any]] = [
        card for result in all_results if result.cards for card in result.cards
    ]
    failed = [result for result in all_results if result.error]

    for attempt in range(1, retries + 1):
        if not failed:
            break
        retry_slots = [slot for result in failed for slot in result.job.slots]
        retry_jobs = build_jobs(retry_slots, 1, attempt)
        print(f"Retrying {len(retry_slots)} failed slot(s) individually (attempt {attempt}/{retries}).", flush=True)
        retry_results = run_job_wave(
            retry_jobs, ROOT, run_dir, concurrency, timeout_seconds, channels,
            codex_command, heartbeat_seconds,
        )
        successful.extend(card for result in retry_results if result.cards for card in result.cards)
        failed = [result for result in retry_results if result.error]

    if failed:
        print("Generation stopped; tracked files were not changed.", file=sys.stderr)
        print(f"Successful outputs remain cached in {run_dir.relative_to(ROOT)} for the next run.", file=sys.stderr)
        return 1

    expected_keys = {(slot["stream"], slot["date"], slot["sequence"]) for slot in slots}
    unique_cards = {
        (card["stream"], card["date"], card["sequence"]): card
        for card in successful
    }
    if set(unique_cards) != expected_keys:
        print("Generation output did not cover every planned slot exactly once; tracked files were not changed.", file=sys.stderr)
        return 1
    try:
        replace_keys = {(slot["stream"], slot["date"]) for slot in slots} if args.regenerate else set()
        staged = stage_and_validate(ROOT, run_dir, list(unique_cards.values()), replace_keys)
        install_cards(ROOT, staged, run_dir, replace_keys)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        print("Generation stopped before commit; inspect the working tree and generation cache.", file=sys.stderr)
        return 1
    print(f"Installed {len(staged)} validated card(s) and updated state/topics.json.")
    shutil.rmtree(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

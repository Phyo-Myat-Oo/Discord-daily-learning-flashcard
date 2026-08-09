#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cardlib import ROOT, all_cards, load_channels, localized
from source_extractors import DEFAULT_MAX_CHARS, EXTRACTORS, extract_structured


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60] or "source"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def files_for(path: Path, max_files: int) -> list[Path]:
    if path.is_file(): return [path]
    if not path.is_dir(): raise ValueError(f"not a file or directory: {path}")
    files = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in EXTRACTORS)
    if len(files) > max_files: raise ValueError(f"directory has {len(files)} supported files; limit is {max_files} (non-recursive)")
    return files


def select_sections(section_args: list[str], sections: list) -> list[int] | None:
    """Resolve 1-based indexes or case-insensitive title fragments."""
    if not section_args:
        return None
    selected: list[int] = []
    for value in section_args:
        if value.isdigit():
            index = int(value) - 1
            if not 0 <= index < len(sections):
                raise ValueError(f"section {value} is outside 1..{len(sections)}")
            selected.append(index)
            continue
        matches = [index for index, section in enumerate(sections) if value.casefold() in section.title.casefold()]
        if not matches:
            raise ValueError(f"no section title contains {value!r}")
        selected.extend(matches)
    return list(dict.fromkeys(selected))


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a local source and ask Codex for candidate cards")
    parser.add_argument("source", type=Path)
    parser.add_argument("--max-cards", type=int, default=15)
    parser.add_argument("--depth", choices=["quick", "normal", "deep"], default="normal")
    parser.add_argument("--priority", choices=["low", "normal", "high"], default="normal")
    parser.add_argument("--max-files", type=int, default=20)
    parser.add_argument("--max-source-chars", type=int, default=DEFAULT_MAX_CHARS, help="normalized text budget passed to Codex")
    parser.add_argument("--section", action="append", default=[], metavar="NUMBER_OR_TEXT", help="select a section by 1-based number or title fragment; repeatable")
    parser.add_argument("--list-sections", action="store_true", help="show detected chapters/sections without generating cards")
    parser.add_argument("--codex-timeout", type=int, default=300, help="stop a stalled Codex generation after this many seconds")
    parser.add_argument("--no-codex", action="store_true", help="extract and print staging location without generating")
    args = parser.parse_args()
    if not 1 <= args.max_cards <= 50:
        parser.error("--max-cards must be between 1 and 50")
    if not 10_000 <= args.max_source_chars <= 500_000:
        parser.error("--max-source-chars must be between 10000 and 500000")
    if not 30 <= args.codex_timeout <= 1800:
        parser.error("--codex-timeout must be between 30 and 1800 seconds")
    try: sources = files_for(args.source.expanduser().resolve(), args.max_files)
    except ValueError as exc: print(exc, file=sys.stderr); return 2
    if not sources: print("No supported source files found.", file=sys.stderr); return 2
    history_path = ROOT / "state/imports.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    generated_root = ROOT / ".generated/imports"
    generated_root.mkdir(parents=True, exist_ok=True)
    for source in sources:
        digest = sha256(source)
        try:
            extracted = extract_structured(source)
            selected = select_sections(args.section, extracted.sections)
            if args.list_sections:
                print(f"\n{source.name}\n  Title: {extracted.title}\n  Type: {extracted.source_type}\n  Sections: {len(extracted.sections)}")
                for index, section in enumerate(extracted.sections, 1):
                    print(f"  {index:>3}. {section.title} [{section.locator or 'no locator'}] — {len(section.text):,} chars")
                continue
            content = extracted.render(selected, args.max_source_chars)
            source_type = extracted.source_type
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            print(f"Extraction failed for {source}: {exc}", file=sys.stderr); continue
        selected_indexes = list(selected if selected is not None else range(len(extracted.sections)))
        selected_metadata = [
            {"number": index + 1, "title": extracted.sections[index].title, "locator": extracted.sections[index].locator}
            for index in selected_indexes
        ]
        selection_key = ",".join(map(str, selected_indexes))
        selection_digest = hashlib.sha256(selection_key.encode()).hexdigest()[:6]
        previous = next(
            (item for item in history["imports"] if item.get("sha256") == digest and (item.get("section_key") == selection_key or (selected is None and "section_key" not in item))),
            None,
        )
        if previous:
            print(f"Skipping identical source selection {source.name}; imported at {previous['processed_at']}.", file=sys.stderr)
            continue
        run_slug = f"{slugify(source.stem)}-{digest[:8]}-{selection_digest}"
        staging = generated_root / f"{run_slug}.txt"
        staging.write_text(content, encoding="utf-8")
        output = ROOT / "cards/imported" / run_slug
        if output.exists():
            print(f"Refusing to overwrite {output}", file=sys.stderr); return 1
        if args.no_codex:
            print(staging); continue
        output.mkdir(parents=True)
        existing = [{**{key: c.get(key) for key in ("id", "category", "topic")}, "question": localized(c, "en", "question")} for _, c in all_cards()]
        dynamic = {"source_type": source_type, "source_file": source.name, "source_title": extracted.title, "selected_sections": selected_metadata, "normalized_text_path": str(staging.relative_to(ROOT)), "output_directory": str(output.relative_to(ROOT)), "depth": args.depth, "max_cards": args.max_cards, "priority": args.priority, "streams": load_channels(), "existing_card_index": existing}
        prompt = (ROOT / "prompts/import_source.md").read_text(encoding="utf-8") + "\n## Dynamic context\n```json\n" + json.dumps(dynamic, indent=2) + "\n```\n"
        try:
            result = subprocess.run(["codex", "exec", "--ephemeral", "--sandbox", "workspace-write", "-C", str(ROOT), "-"], input=prompt, text=True, timeout=args.codex_timeout)
        except subprocess.TimeoutExpired:
            if not any(output.iterdir()):
                output.rmdir()
            print(f"Codex timed out after {args.codex_timeout}s for {source.name}; rerun the same command safely.", file=sys.stderr)
            continue
        if result.returncode:
            empty_output = not any(output.iterdir())
            if empty_output:
                output.rmdir()
            detail = "no candidate files were created" if empty_output else f"partial candidates remain in {output} for inspection"
            print(f"Codex failed for {source.name}; {detail}.", file=sys.stderr); continue
        validation = subprocess.run([sys.executable, str(ROOT / "scripts/validate_cards.py"), str(output)])
        if validation.returncode:
            print(f"Candidate validation failed for {source.name}; history was not updated.", file=sys.stderr); continue
        count = len(list(output.glob("*.json")))
        history["imports"].append({"source_file": source.name, "source_title": extracted.title, "source_type": source_type, "sha256": digest, "section_key": selection_key, "processed_at": datetime.now(timezone.utc).isoformat(), "cards_generated": count, "output_directory": str(output.relative_to(ROOT)), "sections": selected_metadata})
        history_path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
        print(f"Created {count} candidate card(s) in {output}")
    return 0


if __name__ == "__main__": raise SystemExit(main())

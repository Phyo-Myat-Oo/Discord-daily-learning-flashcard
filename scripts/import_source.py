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

from cardlib import ROOT, all_cards, load_channels
from source_extractors import EXTRACTORS, extract


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a local source and ask Codex for candidate cards")
    parser.add_argument("source", type=Path)
    parser.add_argument("--max-cards", type=int, default=15)
    parser.add_argument("--depth", choices=["quick", "normal", "deep"], default="normal")
    parser.add_argument("--priority", choices=["low", "normal", "high"], default="normal")
    parser.add_argument("--max-files", type=int, default=20)
    parser.add_argument("--no-codex", action="store_true", help="extract and print staging location without generating")
    args = parser.parse_args()
    if not 1 <= args.max_cards <= 50:
        parser.error("--max-cards must be between 1 and 50")
    try: sources = files_for(args.source.expanduser().resolve(), args.max_files)
    except ValueError as exc: print(exc, file=sys.stderr); return 2
    if not sources: print("No supported source files found.", file=sys.stderr); return 2
    history_path = ROOT / "state/imports.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    generated_root = ROOT / ".generated/imports"
    generated_root.mkdir(parents=True, exist_ok=True)
    for source in sources:
        digest = sha256(source)
        previous = next((item for item in history["imports"] if item.get("sha256") == digest), None)
        if previous:
            print(f"Skipping identical source {source.name}; imported at {previous['processed_at']}.", file=sys.stderr); continue
        try: source_type, content = extract(source)
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            print(f"Extraction failed for {source}: {exc}", file=sys.stderr); continue
        run_slug = f"{slugify(source.stem)}-{digest[:8]}"
        staging = generated_root / f"{run_slug}.txt"
        staging.write_text(content, encoding="utf-8")
        output = ROOT / "cards/imported" / run_slug
        if output.exists():
            print(f"Refusing to overwrite {output}", file=sys.stderr); return 1
        if args.no_codex:
            print(staging); continue
        output.mkdir(parents=True)
        existing = [{key: c.get(key) for key in ("id", "category", "topic", "question")} for _, c in all_cards()]
        dynamic = {"source_type": source_type, "source_file": source.name, "normalized_text_path": str(staging.relative_to(ROOT)), "output_directory": str(output.relative_to(ROOT)), "depth": args.depth, "max_cards": args.max_cards, "priority": args.priority, "streams": load_channels(), "existing_card_index": existing}
        prompt = (ROOT / "prompts/import_source.md").read_text(encoding="utf-8") + "\n## Dynamic context\n```json\n" + json.dumps(dynamic, indent=2) + "\n```\n"
        result = subprocess.run(["codex", "exec", "--ephemeral", "--sandbox", "workspace-write", "-C", str(ROOT), "-"], input=prompt, text=True)
        if result.returncode:
            print(f"Codex failed for {source.name}; candidates remain in {output} for inspection.", file=sys.stderr); continue
        validation = subprocess.run([sys.executable, str(ROOT / "scripts/validate_cards.py"), str(output)])
        if validation.returncode:
            print(f"Candidate validation failed for {source.name}; history was not updated.", file=sys.stderr); continue
        count = len(list(output.glob("*.json")))
        history["imports"].append({"source_file": source.name, "source_type": source_type, "sha256": digest, "processed_at": datetime.now(timezone.utc).isoformat(), "cards_generated": count, "output_directory": str(output.relative_to(ROOT))})
        history_path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
        print(f"Created {count} candidate card(s) in {output}")
    return 0


if __name__ == "__main__": raise SystemExit(main())

#!/usr/bin/env python3
"""Scan local neuroscience books into an ignored, source-grounded catalog."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cardlib import ROOT
from source_extractors import EXTRACTORS, extract_structured

CONFIG_PATH = ROOT / "config/neuroscience_sources.json"
GENERATED_ROOT = ROOT / ".generated/neuroscience"
CATALOG_PATH = GENERATED_ROOT / "catalog.json"


def page_metrics(text: str) -> dict[str, Any]:
    """Estimate technical reading effort from extractable page features."""
    words = len(re.findall(r"\b[\w'-]+\b", text))
    equation_lines = sum(bool(re.search(r"(?:=|∑|√|∫|∂|\bexp\b|\blog\b)", line)) for line in text.splitlines())
    figure_count = len(re.findall(r"\b(?:figure|fig\.|table)\s*\d", text, re.I))
    code_lines = sum(bool(re.match(r"\s*(?:>>>|import |from \w+ import|def |class |for |while |if |[\w.]+\s*=)", line)) for line in text.splitlines())
    estimated = words / 160 + min(equation_lines, 12) * 0.35 + min(figure_count, 6) * 0.5 + min(code_lines, 30) * 0.08
    estimated = round(min(12.0, max(1.0, estimated)), 1)
    density = "high" if estimated >= 7 else "medium" if estimated >= 4 else "low"
    return {
        "word_count": words,
        "equation_lines": equation_lines,
        "figure_table_refs": figure_count,
        "code_lines": code_lines,
        "estimated_minutes": estimated,
        "density": density,
    }


def section_pages(text: str) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for piece in re.split(r"(?=\[Page \d+\])", text):
        marker = re.match(r"\[Page (\d+)\]\s*", piece)
        if marker:
            body = piece[marker.end():].strip()
            pages.append({"page": int(marker.group(1)), **page_metrics(body)})
    return pages


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def match_source(name: str, title: str, definitions: dict[str, dict[str, Any]]) -> str | None:
    haystack = normalized(f"{name} {title}")
    matches: list[tuple[int, str]] = []
    for source_id, definition in definitions.items():
        aliases = [definition["title"], *definition.get("aliases", [])]
        score = max((len(normalized(alias)) for alias in aliases if normalized(alias) in haystack), default=0)
        if score:
            matches.append((score, source_id))
    return max(matches)[1] if matches else None


def scan(source_dir: Path, max_files: int = 20) -> tuple[dict[str, Any], list[str]]:
    if not source_dir.is_dir():
        raise ValueError(f"not a directory: {source_dir}")
    definitions = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["sources"]
    files = sorted(path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() in EXTRACTORS)
    if len(files) > max_files:
        raise ValueError(f"found {len(files)} supported files; maximum is {max_files} (scan is non-recursive)")
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    source_cache = GENERATED_ROOT / "sources"
    source_cache.mkdir(parents=True, exist_ok=True)
    entries: dict[str, Any] = {}
    warnings: list[str] = []
    for path in files:
        try:
            extracted = extract_structured(path)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"{path.name}: extraction failed: {exc}")
            continue
        source_id = match_source(path.name, extracted.title, definitions)
        if not source_id:
            warnings.append(f"{path.name}: not recognized as a configured neuroscience source")
            continue
        if source_id in entries:
            warnings.append(f"{path.name}: duplicates configured source {source_id}; keeping the first match")
            continue
        digest = sha256(path)
        sections = [
            {"number": index, "title": section.title, "locator": section.locator, "text": section.text, "pages": section_pages(section.text)}
            for index, section in enumerate(extracted.sections, 1)
        ]
        cached_path = source_cache / f"{source_id}-{digest[:12]}.json"
        cached_path.write_text(json.dumps({
            "source_id": source_id,
            "title": extracted.title,
            "source_type": extracted.source_type,
            "filename": path.name,
            "sha256": digest,
            "sections": sections,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        entries[source_id] = {
            "source_id": source_id,
            "configured_title": definitions[source_id]["title"],
            "extracted_title": extracted.title,
            "source_type": extracted.source_type,
            "filename": path.name,
            "sha256": digest,
            "cache_file": str(cached_path.relative_to(ROOT)),
            "section_count": len(sections),
            "sections": [{key: section[key] for key in ("number", "title", "locator")} for section in sections],
            "official_url": definitions[source_id]["official_url"],
        }
    missing = [source_id for source_id, definition in definitions.items() if definition.get("required") and source_id not in entries]
    catalog = {
        "version": 1,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "source_directory": str(source_dir),
        "sources": entries,
        "missing_required": missing,
    }
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return catalog, warnings


def print_catalog(catalog: dict[str, Any]) -> None:
    print(f"Recognized neuroscience sources: {len(catalog.get('sources', {}))}")
    for source_id, entry in catalog.get("sources", {}).items():
        print(f"  {source_id}: {entry['filename']} ({entry['section_count']} sections)")
    missing = catalog.get("missing_required", [])
    if missing:
        print("Missing required sources:")
        definitions = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["sources"]
        for source_id in missing:
            print(f"  {definitions[source_id]['title']}")
            print(f"    {definitions[source_id]['official_url']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan", help="extract and catalog a directory of books")
    scan_parser.add_argument("source_dir", type=Path)
    scan_parser.add_argument("--max-files", type=int, default=20)
    subparsers.add_parser("status", help="show the most recent ignored catalog")
    args = parser.parse_args()
    if args.command == "status":
        if not CATALOG_PATH.exists():
            print("No neuroscience source catalog exists. Run the scan command first.", file=sys.stderr)
            return 2
        print_catalog(json.loads(CATALOG_PATH.read_text(encoding="utf-8")))
        return 0
    try:
        catalog, warnings = scan(args.source_dir.expanduser().resolve(), args.max_files)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    print_catalog(catalog)
    return 2 if catalog["missing_required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

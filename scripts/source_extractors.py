#!/usr/bin/env python3
"""Format-specific extraction into compact, normalized text."""
from __future__ import annotations

import json
from pathlib import Path

MAX_CHARS = 300_000


def _trim(text: str) -> str:
    text = text.replace("\x00", "")
    return text[:MAX_CHARS] + ("\n[content truncated by safety limit]" if len(text) > MAX_CHARS else "")


def extract_text(path: Path) -> str:
    return _trim(path.read_text(encoding="utf-8", errors="replace"))


def extract_notebook(path: Path) -> str:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    sections: list[str] = []
    for index, cell in enumerate(notebook.get("cells", [])):
        kind = cell.get("cell_type")
        source = "".join(cell.get("source", [])).strip()
        if not source: continue
        if kind == "markdown":
            sections.append(f"[Cell {index} | markdown]\n{source}")
        elif kind == "code":
            # Keep useful code in order; exclude bulky/binary output and metadata.
            output_text: list[str] = []
            for output in cell.get("outputs", [])[:3]:
                value = output.get("text") or output.get("data", {}).get("text/plain")
                if value:
                    rendered = "".join(value) if isinstance(value, list) else str(value)
                    output_text.append(rendered[:2000])
            block = f"[Cell {index} | code]\n{source[:8000]}"
            if output_text: block += "\n[Useful text output]\n" + "\n".join(output_text)
            sections.append(block)
    return _trim("\n\n".join(sections))


def extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF support requires: python -m pip install -r requirements.txt") from exc
    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if text: pages.append(f"[Page {index + 1}]\n{text}")
        if sum(map(len, pages)) >= MAX_CHARS: break
    if not pages: raise RuntimeError("PDF contained no extractable text (it may require OCR)")
    return _trim("\n\n".join(pages))


EXTRACTORS = {".pdf": extract_pdf, ".ipynb": extract_notebook, ".md": extract_text, ".txt": extract_text, ".py": extract_text}


def extract(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix not in EXTRACTORS: raise ValueError(f"unsupported format: {suffix}")
    return suffix.lstrip("."), EXTRACTORS[suffix](path)


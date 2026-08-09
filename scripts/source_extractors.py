#!/usr/bin/env python3
"""Format-specific extraction into structured, compact, normalized source text."""
from __future__ import annotations

import html
import json
import re
import subprocess
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

DEFAULT_MAX_CHARS = 120_000


@dataclass
class Section:
    title: str
    text: str
    locator: str = ""


@dataclass
class ExtractedSource:
    source_type: str
    title: str
    sections: list[Section] = field(default_factory=list)

    def render(self, selected: list[int] | None = None, max_chars: int = DEFAULT_MAX_CHARS) -> str:
        indexes = selected if selected is not None else list(range(len(self.sections)))
        blocks = [f"[Source title] {self.title}"]
        used = len(blocks[0])
        for index in indexes:
            section = self.sections[index]
            marker = f"[Section {index + 1}: {section.title}]"
            if section.locator:
                marker += f"\n[Locator: {section.locator}]"
            block = f"{marker}\n{section.text.strip()}"
            if used + len(block) > max_chars:
                remaining = max_chars - used
                if remaining > 1000:
                    blocks.append(block[:remaining] + "\n[section truncated by source limit]")
                blocks.append("[additional source sections omitted by safety limit]")
                break
            blocks.append(block)
            used += len(block)
        return "\n\n".join(blocks)


def _clean_text(text: str) -> str:
    text = html.unescape(text).replace("\x00", "").replace("\r", "\n")
    text = re.sub(r"(?<=\w)-\n(?=[a-z])", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _plain_source(path: Path) -> ExtractedSource:
    text = _clean_text(path.read_text(encoding="utf-8", errors="replace"))
    # Markdown headings provide useful boundaries; plain text/code remains one section.
    if path.suffix.lower() == ".md":
        matches = list(re.finditer(r"(?m)^(#{1,3})\s+(.+?)\s*$", text))
        if matches:
            sections = []
            for pos, match in enumerate(matches):
                end = matches[pos + 1].start() if pos + 1 < len(matches) else len(text)
                body = text[match.end():end].strip()
                if body:
                    sections.append(Section(match.group(2), body, f"heading: {match.group(2)}"))
            return ExtractedSource(path.suffix.lstrip("."), path.stem, sections)
    return ExtractedSource(path.suffix.lstrip("."), path.stem, [Section(path.name, text)])


def _notebook(path: Path) -> ExtractedSource:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    sections: list[Section] = []
    current_title = "Notebook introduction"
    current: list[str] = []
    first_cell = 0

    def flush(last_cell: int) -> None:
        nonlocal current
        body = _clean_text("\n\n".join(current))
        if body:
            sections.append(Section(current_title, body, f"cells {first_cell}-{last_cell}"))
        current = []

    for index, cell in enumerate(notebook.get("cells", [])):
        kind = cell.get("cell_type")
        source = "".join(cell.get("source", [])).strip()
        if not source:
            continue
        heading = re.match(r"^#{1,3}\s+(.+)$", source, re.M) if kind == "markdown" else None
        if heading:
            flush(index - 1)
            current_title = heading.group(1).strip()
            first_cell = index
        if kind == "markdown":
            current.append(f"[Cell {index} | markdown]\n{source}")
        elif kind == "code":
            outputs: list[str] = []
            for output in cell.get("outputs", [])[:3]:
                value = output.get("text") or output.get("data", {}).get("text/plain")
                if value:
                    rendered = "".join(value) if isinstance(value, list) else str(value)
                    outputs.append(rendered[:1500])
            block = f"[Cell {index} | code]\n{source[:8000]}"
            if outputs:
                block += "\n[Useful text output]\n" + "\n".join(outputs)
            current.append(block)
    flush(len(notebook.get("cells", [])) - 1)
    return ExtractedSource("ipynb", notebook.get("metadata", {}).get("title", path.stem), sections)


def _remove_repeated_margins(pages: list[list[str]]) -> list[list[str]]:
    """Remove short lines repeated in page headers/footers on many pages."""
    candidates: Counter[str] = Counter()
    for lines in pages:
        edge = lines[:3] + lines[-3:]
        candidates.update({line.strip() for line in edge if 2 < len(line.strip()) < 100})
    threshold = max(4, len(pages) // 5)
    repeated = {line for line, count in candidates.items() if count >= threshold}
    return [[line for line in lines if line.strip() not in repeated] for lines in pages]


def _pdf(path: Path) -> ExtractedSource:
    try:
        from pypdf import PdfReader
    except ImportError:
        return _pdf_poppler(path)
    reader = PdfReader(str(path))
    raw_pages = [(page.extract_text() or "").splitlines() for page in reader.pages]
    raw_pages = _remove_repeated_margins(raw_pages)
    page_text = [_clean_text("\n".join(lines)) for lines in raw_pages]
    if not any(page_text):
        raise RuntimeError("PDF contained no extractable text (it may require OCR)")
    title = str((reader.metadata or {}).get("/Title") or path.stem)

    # Prefer the PDF outline because it retains reliable page boundaries.
    starts: list[tuple[int, str]] = []
    def walk(items: list, depth: int = 0) -> None:
        for item in items:
            if isinstance(item, list):
                if depth < 1:
                    walk(item, depth + 1)
                continue
            try:
                page_number = reader.get_destination_page_number(item)
                outline_title = str(getattr(item, "title", "")).strip()
            except Exception:
                continue
            if outline_title and page_number >= 0:
                starts.append((page_number, outline_title))
    try:
        walk(reader.outline)
    except Exception:
        starts = []
    starts = sorted(set(starts))
    sections: list[Section] = []
    if starts:
        for position, (start, section_title) in enumerate(starts):
            end = starts[position + 1][0] if position + 1 < len(starts) else len(page_text)
            if end <= start:
                continue
            body = "\n\n".join(f"[Page {page + 1}]\n{page_text[page]}" for page in range(start, end) if page_text[page])
            if body:
                sections.append(Section(section_title, body, f"pages {start + 1}-{end}"))
    else:
        # Page windows prevent a long PDF from becoming one unmanageable block.
        window = 12
        for start in range(0, len(page_text), window):
            end = min(start + window, len(page_text))
            body = "\n\n".join(f"[Page {page + 1}]\n{page_text[page]}" for page in range(start, end) if page_text[page])
            if body:
                sections.append(Section(f"Pages {start + 1}–{end}", body, f"pages {start + 1}-{end}"))
    return ExtractedSource("pdf", title, sections)


def _pdf_poppler(path: Path) -> ExtractedSource:
    """Dependency-free fallback on Ubuntu when pypdf is not installed."""
    try:
        completed = subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("PDF support requires pypdf or Ubuntu's poppler-utils package") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"pdftotext failed: {exc.stderr.strip()}") from exc
    raw_pages = [page.splitlines() for page in completed.stdout.split("\f") if page.strip()]
    raw_pages = _remove_repeated_margins(raw_pages)
    page_text = [_clean_text("\n".join(lines)) for lines in raw_pages]
    page_text = [page for page in page_text if page]
    if not page_text:
        raise RuntimeError("PDF contained no extractable text (it may require OCR)")
    title = path.stem
    try:
        metadata = subprocess.run(["pdfinfo", str(path)], check=True, capture_output=True, text=True).stdout
        match = re.search(r"(?m)^Title:\s*(.+)$", metadata)
        if match:
            title = match.group(1).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    chapter_pattern = re.compile(r"^(?:chapter\s+)?(\d{1,3})\s*[–—-]\s*([^.].{2,90})$", re.I)
    starts: list[tuple[int, str]] = []
    last_number = 0
    for page_index, page in enumerate(page_text):
        candidates: dict[int, str] = {}
        for line in page.splitlines()[:25]:
            match = chapter_pattern.match(line.strip())
            if match:
                candidates[int(match.group(1))] = f"{match.group(1)} — {match.group(2).strip()}"
        # Contents pages contain many chapter lines; a chapter opener repeats one title at most.
        if len(candidates) <= 2:
            for number in sorted(candidates):
                if number == last_number + 1:
                    starts.append((page_index, candidates[number]))
                    last_number = number
                    break
    sections = []
    if len(starts) >= 3:
        if starts[0][0] > 0:
            front = "\n\n".join(f"[Page {page + 1}]\n{page_text[page]}" for page in range(starts[0][0]))
            sections.append(Section("Front matter", front, f"pages 1-{starts[0][0]}"))
        for position, (start, chapter_title) in enumerate(starts):
            end = starts[position + 1][0] if position + 1 < len(starts) else len(page_text)
            body = "\n\n".join(f"[Page {page + 1}]\n{page_text[page]}" for page in range(start, end))
            sections.append(Section(chapter_title, body, f"pages {start + 1}-{end}"))
    else:
        window = 12
        for start in range(0, len(page_text), window):
            end = min(start + window, len(page_text))
            body = "\n\n".join(f"[Page {page + 1}]\n{page_text[page]}" for page in range(start, end))
            sections.append(Section(f"Pages {start + 1}–{end}", body, f"pages {start + 1}-{end}"))
    return ExtractedSource("pdf", title, sections)


class _HTMLText(HTMLParser):
    BLOCKS = {"p", "div", "section", "article", "li", "pre", "code", "blockquote", "h1", "h2", "h3", "h4", "br"}
    SKIP = {"script", "style", "svg", "canvas"}
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self.skip += 1
        elif not self.skip and tag in self.BLOCKS:
            self.parts.append("\n")
    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif not self.skip and tag in self.BLOCKS:
            self.parts.append("\n")
    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def _epub(path: Path) -> ExtractedSource:
    with zipfile.ZipFile(path) as archive:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next(element for element in container.iter() if element.tag.endswith("rootfile"))
        package_path = rootfile.attrib["full-path"]
        package_dir = str(Path(package_path).parent)
        package = ET.fromstring(archive.read(package_path))
        manifest = {item.attrib.get("id"): item.attrib for item in package.iter() if item.tag.endswith("item")}
        spine = [item.attrib.get("idref") for item in package.iter() if item.tag.endswith("itemref")]
        title_node = next((node for node in package.iter() if node.tag.endswith("title") and node.text), None)
        title = title_node.text.strip() if title_node is not None else path.stem
        sections: list[Section] = []
        for item_id in spine:
            item = manifest.get(item_id or "", {})
            href = item.get("href")
            if not href:
                continue
            member = str(Path(package_dir, href)) if package_dir != "." else href
            try:
                raw = archive.read(member).decode("utf-8", errors="replace")
            except KeyError:
                continue
            parser = _HTMLText()
            parser.feed(raw)
            text = _clean_text("".join(parser.parts))
            if len(text) < 80:
                continue
            heading = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", raw, re.I | re.S)
            section_title = _clean_text(re.sub(r"<[^>]+>", " ", heading.group(1))) if heading else Path(href).stem
            sections.append(Section(section_title or Path(href).stem, text, f"EPUB item: {href}"))
    if not sections:
        raise RuntimeError("EPUB contained no readable spine documents")
    return ExtractedSource("epub", title, sections)


EXTRACTORS: dict[str, Callable[[Path], ExtractedSource]] = {
    ".pdf": _pdf,
    ".epub": _epub,
    ".ipynb": _notebook,
    ".md": _plain_source,
    ".txt": _plain_source,
    ".py": _plain_source,
}


def extract_structured(path: Path) -> ExtractedSource:
    suffix = path.suffix.lower()
    if suffix not in EXTRACTORS:
        raise ValueError(f"unsupported format: {suffix}")
    return EXTRACTORS[suffix](path)


def extract(path: Path, selected: list[int] | None = None, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, str]:
    """Compatibility wrapper returning source type and rendered normalized text."""
    result = extract_structured(path)
    return result.source_type, result.render(selected, max_chars)

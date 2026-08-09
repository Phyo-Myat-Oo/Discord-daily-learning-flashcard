#!/usr/bin/env python3
"""Shared card discovery, validation helpers, and Discord formatting."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "cards"
CHANNELS_FILE = ROOT / "config/channels.json"
VALID_CATEGORIES = {"linux", "networking", "git", "docker", "python", "ai", "mlops", "ai-engineering", "review"}
VALID_DIFFICULTIES = {"beginner", "intermediate", "advanced"}
VALID_STATUSES = {"candidate", "approved", "rejected", "scheduled"}
VALID_PRIORITIES = {"low", "normal", "high"}
BASE_REQUIRED = {"id", "stream", "language", "category", "topic", "difficulty", "example", "tags", "status"}
LEGACY_REQUIRED = BASE_REQUIRED | {"title", "summary", "explanation", "use_case", "question", "answer"}
REQUIRED = LEGACY_REQUIRED  # Backward-compatible import for older scripts.
RICH_REQUIRED = {"title", "summary", "explanation", "how_it_works", "use_case", "common_mistake", "practical_tip", "question", "answer"}
EMOJI = {"linux": "🐧", "networking": "🌐", "git": "🌿", "docker": "🐳", "python": "🐍", "ai": "🤖", "mlops": "⚙️", "ai-engineering": "🧩", "review": "🧠"}


def card_paths() -> list[Path]:
    return sorted(p for p in CARDS.rglob("*.json") if p.name != "schema.json")


def load_card(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("top-level JSON must be an object")
    return value


def all_cards() -> Iterable[tuple[Path, dict[str, Any]]]:
    for path in card_paths():
        yield path, load_card(path)


def load_channels() -> dict[str, dict[str, Any]]:
    with CHANNELS_FILE.open(encoding="utf-8") as handle:
        config = json.load(handle)
    streams = config.get("streams")
    if not isinstance(streams, dict) or not streams:
        raise ValueError("config/channels.json must contain a non-empty streams object")
    return streams


def find_card(day: str, stream: str) -> tuple[Path, dict[str, Any]] | None:
    matches = [(p, c) for p, c in all_cards() if c.get("date") == day and c.get("stream") == stream and c.get("status") in {"approved", "scheduled"}]
    if len(matches) > 1:
        raise ValueError(f"multiple sendable cards found for {stream} on {day}")
    return matches[0] if matches else None


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _safe_inline(value: Any) -> str:
    text = str(value).replace("`", "'").replace("||", "¦¦").replace("@", "@\u200b").strip()
    return re.sub(r"([\\*_~])", r"\\\1", text)


def _code(value: Any) -> str:
    return str(value).replace("```", "` ` `").strip()


def is_bilingual(card: dict[str, Any]) -> bool:
    return card.get("language") == "bilingual" and isinstance(card.get("content"), dict)


def localized(card: dict[str, Any], language: str, field: str, default: str = "") -> str:
    if is_bilingual(card):
        block = card.get("content", {}).get(language, {})
        return str(block.get(field, default)) if isinstance(block, dict) else default
    return str(card.get(field, default))


def _rich_description(card: dict[str, Any], language: str) -> str:
    labels = {
        "en": {"learn": "What will you learn?", "works": "How it works", "case": "Real-world scenario", "result": "How to interpret it", "mistake": "Common mistake", "tip": "Practical tip", "recall": "Recall"},
        "my": {"learn": "ဘာကို လေ့လာမလဲ?", "works": "ဘယ်လိုအလုပ်လုပ်သလဲ?", "case": "လက်တွေ့အခြေအနေ", "result": "ရလဒ်ကို ဘယ်လိုနားလည်မလဲ?", "mistake": "မကြာခဏ မှားတတ်သည့်အချက်", "tip": "လက်တွေ့အသုံးဝင်သော အကြံပြုချက်", "recall": "ပြန်လည်မှတ်မိခြင်း"},
    }[language]
    block = card["content"][language]
    lines = [f"**{labels['learn']}**", _safe_inline(block["summary"]), "", f"**{labels['works']}**", _safe_inline(block["explanation"])]
    if block.get("how_it_works"):
        lines += ["", _safe_inline(block["how_it_works"])]
    if card.get("command"):
        lines += ["", "**Command**", f"```bash\n{_code(card['command'])}\n```"]
    if card.get("flags"):
        lines += ["", "**Flags**"] + [f"`{_safe_inline(item['flag'])}` → {_safe_inline(item.get(language, item.get('meaning', '')))}" for item in card["flags"]]
    lines += ["", f"**{labels['case']}**", _safe_inline(block["use_case"])]
    if card.get("example"):
        lines += [f"```{'bash' if card.get('command') else 'text'}\n{_code(card['example'])}\n```"]
    if block.get("expected_result"):
        lines += [f"**{labels['result']}**", _safe_inline(block["expected_result"])]
    lines += ["", f"**{labels['mistake']}**", _safe_inline(block["common_mistake"]), "", f"**{labels['tip']}**", _safe_inline(block["practical_tip"]), "", f"🧠 **{labels['recall']}**", _safe_inline(block["question"]), "", f"||{_safe_inline(block['answer'])}||"]
    return "\n".join(lines)


def build_discord_payload(card: dict[str, Any]) -> dict[str, Any]:
    """Build the webhook JSON body; rich bilingual cards use two embeds."""
    if not is_bilingual(card):
        return {"content": format_discord(card), "allowed_mentions": {"parse": []}}
    category = card["category"]
    footer = " • ".join([category.replace("-", " ").title(), f"Sequence {card.get('sequence', '—')}", card["difficulty"].title()])
    source = card.get("source_title")
    if source:
        footer += f" • Source: {source}"
    embeds = [
        {"title": f"🇬🇧 {localized(card, 'en', 'title')}", "description": _rich_description(card, "en"), "color": 0x3498DB, "footer": {"text": footer}},
        {"title": f"🇲🇲 {localized(card, 'my', 'title')}", "description": _rich_description(card, "my"), "color": 0xF1C40F, "footer": {"text": footer}},
    ]
    return {"content": f"{EMOJI.get(category, '📚')} **{category.replace('-', ' ').title()} — Daily Learning**", "embeds": embeds, "allowed_mentions": {"parse": []}}


def format_discord(card: dict[str, Any]) -> str:
    if is_bilingual(card):
        payload = build_discord_payload(card)
        chunks = [payload.get("content", "")]
        for embed in payload["embeds"]:
            chunks += ["", f"## {embed['title']}", embed["description"], f"_{embed['footer']['text']}_"]
        return "\n".join(chunks)
    category = card["category"]
    heading = "အပတ်စဉ် ပြန်လည်မှတ်မိခြင်း" if category == "review" else f"{category.replace('-', ' ').title()} — နေ့စဉ်လေ့လာခြင်း"
    lines = [f"{EMOJI.get(category, '📚')} **{heading}**", "", f"**{_safe_inline(card['title'])}**", "", "**ဘာကို လေ့လာမလဲ?**", _safe_inline(card["summary"])]
    if card.get("command"):
        lines += ["", "**အသုံးဝင်သော command:**", f"```bash\n{_code(card['command'])}\n```"]
    if card.get("flags"):
        lines += ["", "**Flags များ:**"] + [f"`{_safe_inline(item['flag'])}` → {_safe_inline(item['meaning'])}" for item in card["flags"]]
    lines += ["", "**ဘာကြောင့် အရေးကြီးသလဲ?**", _safe_inline(card["explanation"]), "", "**လက်တွေ့အသုံးချမှု**", _safe_inline(card["use_case"])]
    if card.get("example"):
        language = "bash" if card.get("command") else "text"
        lines += [f"```{language}\n{_code(card['example'])}\n```"]
    lines += ["", "🧠 **ပြန်လည်မှတ်မိခြင်း**"]
    if category == "review" and card.get("review_items"):
        for index, item in enumerate(card["review_items"], 1):
            lines += [f"{index}. {_safe_inline(item['question'])}", f"||{_safe_inline(item['answer'])}||", ""]
        if lines[-1] == "": lines.pop()
    else:
        lines += [_safe_inline(card["question"]), "", f"||{_safe_inline(card['answer'])}||"]
    lines += ["", " • ".join([category.replace("-", " ").title(), *[str(t).title() for t in card.get("tags", [])[:2]], card["difficulty"].title()])]
    return "\n".join(lines)


def normalized_words(value: str) -> set[str]:
    stop = {"the", "a", "an", "to", "of", "and", "in", "with", "for", "is", "what", "how", "why", "using", "use"}
    return {word for word in re.findall(r"[a-z0-9]+", value.lower()) if len(word) > 2 and word not in stop}

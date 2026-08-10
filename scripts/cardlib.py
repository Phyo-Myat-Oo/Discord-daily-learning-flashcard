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
VALID_CATEGORIES = {"linux", "networking", "git", "docker", "python", "ai", "mlops", "ai-engineering", "neuroscience", "review"}
VALID_DIFFICULTIES = {"beginner", "intermediate", "advanced"}
VALID_STATUSES = {"candidate", "approved", "rejected", "scheduled"}
VALID_PRIORITIES = {"low", "normal", "high"}
BASE_REQUIRED = {"id", "stream", "language", "category", "topic", "difficulty", "example", "tags", "status"}
LEGACY_REQUIRED = BASE_REQUIRED | {"title", "summary", "explanation", "use_case", "question", "answer"}
REQUIRED = LEGACY_REQUIRED  # Backward-compatible import for older scripts.
RICH_REQUIRED = {"title", "learning_objective", "simple_explanation", "how_it_works", "visual", "use_case", "expected_result", "what_to_notice", "common_mistake", "practical_tip", "question", "answer"}
EMOJI = {"linux": "🐧", "networking": "🌐", "git": "🌿", "docker": "🐳", "python": "🐍", "ai": "🤖", "mlops": "⚙️", "ai-engineering": "🧩", "neuroscience": "🧬", "review": "🧠"}


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


def load_channels(include_disabled: bool = False) -> dict[str, dict[str, Any]]:
    with CHANNELS_FILE.open(encoding="utf-8") as handle:
        config = json.load(handle)
    streams = config.get("streams")
    if not isinstance(streams, dict) or not streams:
        raise ValueError("config/channels.json must contain a non-empty streams object")
    if include_disabled:
        return streams
    return {name: config for name, config in streams.items() if config.get("enabled", True)}


def _study_plan_description(card: dict[str, Any]) -> str:
    plan = card["study_plan"]
    source_label = _safe_inline(plan["source_title"])
    source_line = f"[{source_label}]({plan['source_url']})" if plan.get("source_url") else source_label
    lines = [
        f"**Day {plan['course_day']} of 182 • Week {plan['course_week']}**",
        f"**Source:** {source_line}",
        f"**Read/watch:** {_safe_inline(plan['source_locator'])}",
        "",
    ]
    for task in plan["tasks"]:
        lines += [
            f"**{task['minutes']} min — {_safe_inline(task['activity'])}**",
            _safe_inline(task["en"]),
        ]
    lines += [
        "",
        "**Finish by producing**",
        _safe_inline(plan["study_output"]["en"]),
    ]
    resource = plan.get("online_resource")
    if isinstance(resource, dict):
        lines += [
            "",
            "**Optional online companion**",
            f"[{_safe_inline(resource['title'])}]({resource['url']})",
            _safe_inline(resource.get("note", "Use this only if the core lesson needs reinforcement.")),
        ]
    if isinstance(plan.get("assessment"), dict) and card.get("review_items"):
        lines += ["", "**Weekly self-assessment — 1 point each**"]
        for index, item in enumerate(card["review_items"], 1):
            lines += [f"{index}. {_safe_inline(item['question'])}", f"||{_safe_inline(item['answer'])}||"]
        lines += ["", f"**Scoring:** {_safe_inline(plan['assessment']['rubric'])}"]
    return "\n".join(lines)


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


def is_rich(card: dict[str, Any]) -> bool:
    return card.get("language") in {"en", "bilingual"} and isinstance(card.get("content"), dict)


def localized(card: dict[str, Any], language: str, field: str, default: str = "") -> str:
    if is_rich(card):
        block = card.get("content", {}).get(language, {})
        return str(block.get(field, default)) if isinstance(block, dict) else default
    return str(card.get(field, default))


def _rich_description(card: dict[str, Any], language: str) -> str:
    labels = {
        "en": {"goal": "By the end", "start": "Start here", "works": "How it works", "visual": "See the idea", "case": "When this is useful", "result": "Expected result", "notice": "Notice this", "mistake": "Common mistake", "tip": "Practical tip", "recall": "Recall"},
        "my": {"goal": "ဒီကတ်အပြီးမှာ", "start": "အရင်ဆုံး နားလည်ရမယ့်အချက်", "works": "ဘယ်လိုအလုပ်လုပ်သလဲ?", "visual": "ပုံဖော်ကြည့်ရအောင်", "case": "ဘယ်အချိန်မှာ အသုံးဝင်သလဲ?", "result": "မျှော်လင့်ရမယ့်ရလဒ်", "notice": "ဒီအချက်ကို သတိထားပါ", "mistake": "မကြာခဏ မှားတတ်သည့်အချက်", "tip": "လက်တွေ့အသုံးဝင်သော အကြံပြုချက်", "recall": "ပြန်လည်မှတ်မိခြင်း"},
    }[language]
    block = card["content"][language]
    lines = [f"**🎯 {labels['goal']}**", _safe_inline(block["learning_objective"]), "", f"**{labels['start']}**", _safe_inline(block["simple_explanation"]), "", f"**{labels['works']}**", _safe_inline(block["how_it_works"])]
    if block.get("visual"):
        lines += ["", f"**{labels['visual']}**", f"```text\n{_code(block['visual'])}\n```"]
    if card.get("command"):
        lines += ["", "**Command**", f"```bash\n{_code(card['command'])}\n```"]
    if card.get("flags"):
        lines += ["", "**Flags**"] + [f"`{_safe_inline(item['flag'])}` → {_safe_inline(item.get(language, item.get('meaning', '')))}" for item in card["flags"]]
    lines += ["", f"**{labels['case']}**", _safe_inline(block["use_case"])]
    if card.get("example"):
        lines += [f"```{'bash' if card.get('command') else 'text'}\n{_code(card['example'])}\n```"]
    lines += [f"**{labels['result']}**", _safe_inline(block["expected_result"]), "", f"**{labels['notice']}**", _safe_inline(block["what_to_notice"])]
    lines += ["", f"**{labels['mistake']}**", _safe_inline(block["common_mistake"]), "", f"**{labels['tip']}**", _safe_inline(block["practical_tip"]), "", f"🧠 **{labels['recall']}**", _safe_inline(block["question"]), "", f"||{_safe_inline(block['answer'])}||"]
    return "\n".join(lines)


def build_discord_payload(card: dict[str, Any]) -> dict[str, Any]:
    """Build the webhook JSON body; rich bilingual cards use two embeds."""
    if not is_rich(card):
        return {"content": format_discord(card), "allowed_mentions": {"parse": []}}
    category = card["category"]
    footer = " • ".join([category.replace("-", " ").title(), f"Sequence {card.get('sequence', '—')}", card["difficulty"].title()])
    source = card.get("source_title")
    if source:
        footer += f" • Source: {source}"
    embeds = [{"title": f"🇬🇧 {localized(card, 'en', 'title')}", "description": _rich_description(card, "en"), "color": 0x3498DB, "footer": {"text": footer}}]
    if is_bilingual(card):
        embeds.append({"title": f"🇲🇲 {localized(card, 'my', 'title')}", "description": _rich_description(card, "my"), "color": 0xF1C40F, "footer": {"text": footer}})
    if isinstance(card.get("study_plan"), dict):
        embeds.append({
            "title": "📖 Today’s 60-minute study plan",
            "description": _study_plan_description(card),
            "color": 0x9B59B6,
            "footer": {"text": "Keep the hour small, focused, and complete."},
        })
    return {"content": f"{EMOJI.get(category, '📚')} **{category.replace('-', ' ').title()} — Daily Learning**", "embeds": embeds, "allowed_mentions": {"parse": []}}


def format_discord(card: dict[str, Any]) -> str:
    if is_rich(card):
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

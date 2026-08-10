#!/usr/bin/env python3
"""Build a source-verified 182-day neuroscience and BCI study plan."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from cardlib import ROOT
from neuroscience_sources import CATALOG_PATH, page_metrics

CURRICULUM_PATH = ROOT / "config/neuroscience_curriculum.json"
ONLINE_RESOURCES_PATH = ROOT / "config/neuroscience_online_resources.json"
PLAN_PATH = ROOT / "state/neuroscience_plan.json"


def words(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", value.casefold()) if len(word) > 2}


def select_section(sections: list[dict[str, Any]], keywords: list[str]) -> dict[str, Any]:
    keyword_words = set().union(*(words(keyword) for keyword in keywords))
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for section in sections:
        title = str(section.get("title", "")).casefold()
        text = str(section.get("text", ""))[:60000].casefold()
        title_words = words(title)
        title_score = len(keyword_words & title_words) * 20
        phrase_score = sum(min(text.count(keyword.casefold()), 30) * 20 for keyword in keywords)
        frequency_score = sum(min(len(re.findall(rf"\b{re.escape(word)}\b", text)), 40) for word in keyword_words)
        scored.append((title_score + phrase_score + frequency_score, -int(section.get("number", 0)), section))
    if not scored or max(scored)[0] == 0:
        raise ValueError(f"could not match source section using keywords: {', '.join(keywords)}")
    return max(scored)[2]


def focused_locator(section: dict[str, Any], topic_index: int, topic_count: int, topic: str) -> str:
    locator = str(section.get("locator", "")).strip()
    match = re.fullmatch(r"pages\s+(\d+)-(\d+)", locator, re.I)
    if match:
        first, last = map(int, match.groups())
        span = max(1, last - first + 1)
        start = first + math.floor(topic_index * span / topic_count)
        end = first + math.floor((topic_index + 1) * span / topic_count) - 1
        end = min(last, start + 7, max(start, end))
        return f"PDF pages {start}–{end} — {section['title']}"
    return f"{section['title']} ({locator or 'section'}) — focus: {topic}"


def configured_section(sections: list[dict[str, Any]], week: dict[str, Any]) -> dict[str, Any] | None:
    numbers = week.get("source_section_numbers")
    if numbers is None and week.get("source_section_number") is not None:
        numbers = [week["source_section_number"]]
    if numbers is None:
        return None
    selected = [item for number in numbers for item in sections if item.get("number") == number]
    if len(selected) != len(numbers):
        raise ValueError(f"missing configured source section(s): {numbers}")
    if len(selected) == 1:
        return selected[0]
    first = re.fullmatch(r"pages\s+(\d+)-(\d+)", str(selected[0]["locator"]), re.I)
    last = re.fullmatch(r"pages\s+(\d+)-(\d+)", str(selected[-1]["locator"]), re.I)
    if not first or not last:
        raise ValueError("multi-section curriculum anchors require PDF page locators")
    return {
        "number": numbers[0],
        "numbers": numbers,
        "title": f"Pages {first.group(1)}–{last.group(2)}",
        "locator": f"pages {first.group(1)}-{last.group(2)}",
        "text": "\n".join(str(item.get("text", "")) for item in selected),
        "pages": [page for item in selected for page in item.get("pages", [])],
    }


def adaptive_assignment(section: dict[str, Any], topic_index: int, topic_count: int, topic: str) -> tuple[str, dict[str, Any]]:
    """Split a section by cumulative estimated effort, not equal page count."""
    pages = list(section.get("pages", []))
    if not pages:
        pieces = re.split(r"(?=\[Page \d+\])", str(section.get("text", "")))
        for piece in pieces:
            marker = re.match(r"\[Page (\d+)\]\s*", piece)
            if marker:
                pages.append({"page": int(marker.group(1)), **page_metrics(piece[marker.end():])})
    if not pages:
        match = re.fullmatch(r"pages\s+(\d+)-(\d+)", str(section.get("locator", "")), re.I)
        if match:
            first, last = map(int, match.groups())
            pages = [{"page": page, "estimated_minutes": 4.0, "word_count": 0, "equation_lines": 0, "figure_table_refs": 0, "code_lines": 0, "density": "medium"} for page in range(first, last + 1)]
    if not pages:
        locator = focused_locator(section, topic_index, topic_count, topic)
        return locator, {"estimated_reading_minutes": 25, "density": "unknown", "word_count": 0, "equation_lines": 0, "figure_table_refs": 0, "code_lines": 0}
    total = sum(float(page.get("estimated_minutes", 1)) for page in pages)
    boundaries = [0]
    for part in range(1, topic_count):
        target = total * part / topic_count
        cumulative = 0.0
        boundary = boundaries[-1] + 1
        for index, page in enumerate(pages):
            cumulative += float(page.get("estimated_minutes", 1))
            if cumulative >= target:
                boundary = max(boundaries[-1] + 1, index + 1)
                break
        boundaries.append(min(boundary, len(pages) - (topic_count - part)))
    boundaries.append(len(pages))
    chosen = pages[boundaries[topic_index]:boundaries[topic_index + 1]]
    raw_minutes = sum(float(page.get("estimated_minutes", 1)) for page in chosen)
    study_minutes = min(30, max(18, round(raw_minutes + 5)))
    density_score = raw_minutes / max(1, len(chosen))
    workload = {
        "estimated_reading_minutes": study_minutes,
        "raw_text_minutes": round(raw_minutes, 1),
        "density": "high" if density_score >= 7 else "medium" if density_score >= 4 else "low",
        "word_count": sum(int(page.get("word_count", 0)) for page in chosen),
        "equation_lines": sum(int(page.get("equation_lines", 0)) for page in chosen),
        "figure_table_refs": sum(int(page.get("figure_table_refs", 0)) for page in chosen),
        "code_lines": sum(int(page.get("code_lines", 0)) for page in chosen),
    }
    printed = [page.get("printed_page") for page in chosen if isinstance(page.get("printed_page"), int)]
    pdf_range = f"PDF viewer pages {chosen[0]['page']}–{chosen[-1]['page']}"
    section_title = str(section.get("title", "")).strip()
    suffix = "" if re.fullmatch(r"Pages\s+\d+[–-]\d+", section_title, re.I) else f" — {section_title}"
    if printed:
        locator = f"Book pages {printed[0]}–{printed[-1]} ({pdf_range}){suffix}"
    else:
        locator = f"{pdf_range}{suffix}"
    return locator, workload


def concept_tasks(topic: str, locator: str, source_minutes: int = 25, first_day: bool = False) -> list[dict[str, Any]]:
    explain_minutes = 40 - source_minutes
    return english_tasks([
        {"minutes": 5, "activity": "Recall", "en": "Before reading, write what you currently believe a neuron does." if first_day else "Without notes, recall yesterday’s main idea.", "my": "မှတ်စုမကြည့်ဘဲ မနေ့က အဓိကအချက်ကို ပြန်စဉ်းစားပါ။"},
        {"minutes": 10, "activity": "Daily lesson", "en": f"Read today’s Discord lesson about {topic}.", "my": f"ဒီနေ့ Discord lesson ထဲက {topic} အကြောင်းကို နားလည်အောင်ဖတ်ပါ။"},
        {"minutes": source_minutes, "activity": "Source study", "en": f"Study {locator}. Stop when this time box ends, even if you want to continue.", "my": f"{locator} ကိုပဲ လေ့လာပါ။ သတ်မှတ်ထားသည့် အပိုင်းပြီးလျှင် ရပ်ပါ။"},
        {"minutes": explain_minutes, "activity": "Active exercise", "en": "Complete the topic-specific active exercise in today’s Discord card and save its stated output.", "my": "ဖြစ်စဉ်အဆင့်ဆင့်ကို ကိုယ့်စကားဖြင့် စာကြောင်းသုံးကြောင်း ရေးပါ။"},
        {"minutes": 5, "activity": "Check", "en": "Complete all three recall checks, then correct only what was missing.", "my": "Recall question ကို ဖြေပြီး လိုနေသည့်အချက်ကိုသာ ပြန်ပြင်ပါ။"},
    ])


def lab_tasks(lab: str) -> list[dict[str, Any]]:
    return english_tasks([
        {"minutes": 5, "activity": "Recall", "en": "Recall the week’s central mechanism without notes.", "my": "ဒီအပတ်ရဲ့ အဓိက mechanism ကို မှတ်စုမကြည့်ဘဲ ပြန်စဉ်းစားပါ။"},
        {"minutes": 10, "activity": "Prepare", "en": "Read the practical briefing and define the expected result.", "my": "လက်တွေ့ညွှန်ကြားချက်ကိုဖတ်ပြီး မျှော်လင့်ရမည့်ရလဒ်ကို သတ်မှတ်ပါ။"},
        {"minutes": 40, "activity": "Practice", "en": lab, "my": f"လက်တွေ့လုပ်ရန် — {lab}"},
        {"minutes": 5, "activity": "Lab log", "en": "Record what happened, what you noticed, and one unanswered question.", "my": "ဖြစ်ပေါ်ခဲ့သည့်ရလဒ်၊ သတိထားမိသည့်အချက်နှင့် မရှင်းသေးသည့်မေးခွန်းတစ်ခုကို ရေးပါ။"},
    ])


def review_tasks(week: int) -> list[dict[str, Any]]:
    return english_tasks([
        {"minutes": 20, "activity": "Self-assessment", "en": f"Answer all five Week {week} questions without notes, then score one point per correct answer.", "my": f"စာအုပ်မဖွင့်ဘဲ Week {week} မေးခွန်းတွေကို ဖြေပါ။"},
        {"minutes": 15, "activity": "Repair", "en": "Open the spoiler answers, revisit only missed ideas, and correct your mental model.", "my": "နားလည်မှုအနည်းဆုံး lesson တစ်ခုကိုသာ ပြန်ကြည့်ပြီး mental model ကို ပြင်ပါ။"},
        {"minutes": 20, "activity": "Synthesize", "en": "Create one diagram connecting the week’s five concepts.", "my": "ဒီအပတ် concept ငါးခုကို ဆက်စပ်ပြသည့် diagram တစ်ခု ဆွဲပါ။"},
        {"minutes": 5, "activity": "Preview", "en": "Read next week’s module title; do not study it yet.", "my": "နောက်အပတ် module title ကိုသာ ကြည့်ပါ။ အကြောင်းအရာကို မစတင်သေးပါနှင့်။"},
    ])


def english_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the neuroscience course and generated cards English-only."""
    return [{key: value for key, value in task.items() if key != "my"} for task in tasks]


def assessment_blueprint(week: int, days: list[dict[str, Any]]) -> dict[str, Any]:
    current = [day for day in days if day["course_week"] == week and day["day_type"] == "concept"]
    candidates = [current[0], current[2], current[4]]
    for earlier_week in (week - 1, week - 4, week - 12):
        earlier = [day for day in days if day["course_week"] == earlier_week and day["day_type"] == "concept"]
        if earlier:
            candidates.append(earlier[min(2, len(earlier) - 1)])
    unique: list[dict[str, Any]] = []
    for day in [*candidates, *current]:
        if day["course_day"] not in {item["course_day"] for item in unique}:
            unique.append(day)
        if len(unique) == 5:
            break
    return {
        "mode": "self-check",
        "score_max": 5,
        "items": [
            {"course_day": day["course_day"], "topic": day["topic"], "module": day["module"], "review_age_days": week * 7 - day["course_day"]}
            for day in unique[:5]
        ],
        "rubric": "Give yourself one point for each answer that states the correct mechanism, not merely a related keyword.",
    }


def build_plan(catalog: dict[str, Any], curriculum: dict[str, Any]) -> dict[str, Any]:
    if catalog.get("missing_required"):
        raise ValueError("missing required sources: " + ", ".join(catalog["missing_required"]))
    weeks = curriculum.get("weeks", [])
    if len(weeks) != 26 or [week.get("week") for week in weeks] != list(range(1, 27)):
        raise ValueError("curriculum must contain consecutively numbered Weeks 1..26")
    days: list[dict[str, Any]] = []
    online_catalog = json.loads(ONLINE_RESOURCES_PATH.read_text(encoding="utf-8"))
    source_summary: dict[str, Any] = {}
    for week in weeks:
        source_id = week["source_id"]
        entry = catalog["sources"].get(source_id)
        if not entry:
            raise ValueError(f"Week {week['week']} requires unavailable source {source_id}")
        cached = json.loads((ROOT / entry["cache_file"]).read_text(encoding="utf-8"))
        try:
            section = configured_section(cached["sections"], week)
        except ValueError as exc:
            raise ValueError(f"Week {week['week']} ({source_id}): {exc}") from exc
        if section is None:
            section = select_section(cached["sections"], week["section_keywords"])
        source_summary[source_id] = {
            "title": entry["configured_title"],
            "sha256": entry["sha256"],
            "official_url": entry["official_url"],
        }
        resource_id = online_catalog.get("week_resources", {}).get(str(week["week"]))
        online_resource = online_catalog.get("resources", {}).get(resource_id)
        if not online_resource:
            raise ValueError(f"Week {week['week']} has no configured online companion for {source_id}")
        online_resource = {key: online_resource[key] for key in ("title", "url", "note")}
        topics = week.get("topics", [])
        if len(topics) != 5:
            raise ValueError(f"Week {week['week']} must contain exactly five concept topics")
        for topic_index, topic in enumerate(topics):
            course_day = len(days) + 1
            locator, workload = adaptive_assignment(section, topic_index, len(topics), topic)
            days.append({
                "course_day": course_day,
                "course_week": week["week"],
                "weekday": topic_index + 1,
                "day_type": "concept",
                "study_duration_minutes": 60,
                "module": week["module"],
                "topic": topic,
                "difficulty": "beginner" if course_day <= 56 else "intermediate" if course_day <= 140 else "advanced",
                "source_id": source_id,
                "source_title": entry["configured_title"],
                "source_locator": locator,
                "source_url": entry["official_url"],
                "online_resource": online_resource,
                "source_section": section["title"],
                "source_section_number": section["number"],
                "source_section_numbers": section.get("numbers", [section["number"]]),
                "workload": workload,
                "assessment": None,
                "tasks": concept_tasks(topic, locator, workload["estimated_reading_minutes"], course_day == 1),
                "study_output": {"en": f"Explain {topic} in your own words using one causal diagram."},
            })
        course_day = len(days) + 1
        lab_locator = f"Practice for Week {week['week']} — {week['module']}"
        days.append({
            "course_day": course_day,
            "course_week": week["week"],
            "weekday": 6,
            "day_type": "practical",
            "study_duration_minutes": 60,
            "module": week["module"],
            "topic": f"Practical: {week['module']}",
            "difficulty": "beginner" if course_day <= 56 else "intermediate" if course_day <= 140 else "advanced",
            "source_id": source_id,
            "source_title": entry["configured_title"],
            "source_locator": lab_locator,
            "source_url": entry["official_url"],
            "online_resource": online_resource,
            "source_section": section["title"],
            "source_section_number": section["number"],
            "source_section_numbers": section.get("numbers", [section["number"]]),
            "workload": None,
            "assessment": None,
            "tasks": lab_tasks(week["lab"]),
            "study_output": {"en": "Save one diagram, notebook result, or experiment log entry."},
        })
        course_day = len(days) + 1
        assessment = assessment_blueprint(week["week"], days)
        days.append({
            "course_day": course_day,
            "course_week": week["week"],
            "weekday": 7,
            "day_type": "review",
            "study_duration_minutes": 60,
            "module": week["module"],
            "topic": f"Review: {week['module']}",
            "difficulty": "beginner" if course_day <= 56 else "intermediate" if course_day <= 140 else "advanced",
            "source_id": source_id,
            "source_title": entry["configured_title"],
            "source_locator": f"Review Week {week['week']} assignments — no new pages",
            "source_url": entry["official_url"],
            "online_resource": online_resource,
            "source_section": section["title"],
            "source_section_number": section["number"],
            "source_section_numbers": section.get("numbers", [section["number"]]),
            "workload": None,
            "assessment": assessment,
            "tasks": review_tasks(week["week"]),
            "study_output": {"en": "Keep one weekly concept map and a list of remaining questions."},
        })
    if len(days) != 182 or any(sum(task["minutes"] for task in day["tasks"]) != 60 for day in days):
        raise ValueError("internal plan error: expected 182 days with exactly 60 minutes each")
    return {
        "version": 1,
        "course_title": curriculum["course_title"],
        "status": "draft",
        "start_date": None,
        "sources": source_summary,
        "days": days,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--output", type=Path, default=PLAN_PATH)
    args = parser.parse_args()
    try:
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        curriculum = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        plan = build_plan(catalog, curriculum)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Cannot build neuroscience plan: {exc}", file=sys.stderr)
        return 2
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(plan['days'])} source-verified study days in {args.output}.")
    print("The plan is still inactive; inspect it before running activate_neuroscience_plan.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

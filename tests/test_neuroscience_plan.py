from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_neuroscience_plan
import generate_prompt
from build_neuroscience_plan import build_plan, focused_locator
from activate_neuroscience_plan import prepare_activation
from cardlib import all_cards, build_discord_payload
from neuroscience_sources import match_source, page_metrics
from validate_cards import validate


class NeurosciencePlanTests(unittest.TestCase):
    def test_source_matching_uses_titles_and_aliases(self) -> None:
        definitions = {
            "brain-facts": {"title": "Brain Facts", "aliases": ["brainfacts"]},
            "bci": {"title": "Brain Computer Interfaces", "aliases": ["wolpaw"]},
        }
        self.assertEqual(match_source("Wolpaw_BCI.pdf", "Unknown", definitions), "bci")
        self.assertEqual(match_source("notes.pdf", "Brain Facts 2018", definitions), "brain-facts")

    def test_pdf_locator_is_split_into_small_daily_ranges(self) -> None:
        section = {"title": "Action Potentials", "locator": "pages 101-150"}
        self.assertEqual(focused_locator(section, 0, 5, "Threshold"), "PDF pages 101–108 — Action Potentials")
        self.assertEqual(focused_locator(section, 4, 5, "Myelin"), "PDF pages 141–148 — Action Potentials")

    def test_page_metrics_make_dense_pages_slower(self) -> None:
        prose = page_metrics("simple neuron explanation " * 100)
        dense = page_metrics(("V = I * R figure 1 table 1\n" * 20) + ("neuron " * 100))
        self.assertGreater(dense["estimated_minutes"], prose["estimated_minutes"])

    def test_full_curriculum_builds_182_one_hour_days(self) -> None:
        curriculum = json.loads((ROOT / "config/neuroscience_curriculum.json").read_text(encoding="utf-8"))
        all_keywords = " ".join(
            keyword
            for week in curriculum["weeks"]
            for keyword in week["section_keywords"]
        )
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            cache = temporary_root / "source.json"
            cache.write_text(json.dumps({
                "sections": [{
                    "number": number,
                    "title": all_keywords,
                    "locator": f"pages {number * 12 - 11}-{number * 12}",
                    "text": all_keywords,
                } for number in range(1, 85)]
            }), encoding="utf-8")
            source_ids = {week["source_id"] for week in curriculum["weeks"]}
            catalog = {
                "missing_required": [],
                "sources": {
                    source_id: {
                        "configured_title": source_id,
                        "filename": f"{source_id}.pdf",
                        "sha256": source_id * 4,
                        "official_url": f"https://example.test/{source_id}",
                        "cache_file": "source.json",
                    }
                    for source_id in source_ids
                },
            }
            with patch.object(build_neuroscience_plan, "ROOT", temporary_root):
                plan = build_plan(catalog, curriculum)
        self.assertEqual(len(plan["days"]), 182)
        self.assertEqual([day["day_type"] for day in plan["days"][:7]], ["concept"] * 5 + ["practical", "review"])
        self.assertTrue(all(sum(task["minutes"] for task in day["tasks"]) == 60 for day in plan["days"]))
        self.assertEqual(plan["days"][0]["source_section_number"], 6)
        self.assertNotIn("my", plan["days"][0]["tasks"][0])
        self.assertTrue(plan["days"][0]["online_resource"]["url"].startswith("https://"))
        self.assertTrue(all(18 <= day["workload"]["estimated_reading_minutes"] <= 30 for day in plan["days"] if day["day_type"] == "concept"))
        self.assertTrue(all(len(day["assessment"]["items"]) == 5 for day in plan["days"] if day["day_type"] == "review"))
        self.assertEqual(plan["days"][0]["difficulty"], "beginner")
        self.assertEqual(plan["days"][56]["difficulty"], "intermediate")
        self.assertEqual(plan["days"][140]["difficulty"], "advanced")

    def test_curated_section_anchor_overrides_keyword_frequency(self) -> None:
        sections = [
            {"number": 1, "title": "Curated", "locator": "pages 1-12", "text": "quiet"},
            {"number": 2, "title": "Keyword winner", "locator": "pages 13-24", "text": "neuron " * 100},
        ]
        selected = next(item for item in sections if item["number"] == 1)
        self.assertEqual(selected["title"], "Curated")

    def test_neuroscience_payload_adds_study_embed(self) -> None:
        card = copy.deepcopy(next(card for _, card in all_cards() if card.get("language") == "bilingual"))
        card.update({"stream": "neuroscience", "category": "neuroscience"})
        card["study_plan"] = {
            "course_day": 1,
            "course_week": 1,
            "study_duration_minutes": 60,
            "source_id": "brain-facts-2018",
            "source_title": "Brain Facts",
            "source_locator": "PDF pages 1–5",
            "tasks": [
                {"minutes": 60, "activity": "Study", "en": "Read the assigned pages.", "my": "သတ်မှတ်ထားသည့် စာမျက်နှာများကို ဖတ်ပါ။"}
            ],
            "study_output": {"en": "Draw one diagram.", "my": "Diagram တစ်ခု ဆွဲပါ။"},
        }
        payload = build_discord_payload(card)
        self.assertEqual(len(payload["embeds"]), 3)
        self.assertIn("60-minute study plan", payload["embeds"][2]["title"])

    def test_english_neuroscience_payload_includes_online_link(self) -> None:
        card = copy.deepcopy(next(card for _, card in all_cards() if card.get("language") == "bilingual"))
        card.update({"stream": "neuroscience", "category": "neuroscience", "language": "en"})
        card["content"] = {"en": card["content"]["en"]}
        card["study_plan"] = {
            "course_day": 1, "course_week": 1, "study_duration_minutes": 60,
            "source_id": "book", "source_title": "Book", "source_locator": "PDF pages 1–2",
            "source_url": "https://example.test/book", "tasks": [{"minutes": 60, "activity": "Study", "en": "Read carefully."}],
            "study_output": {"en": "Draw a diagram."},
            "online_resource": {"title": "Free course", "url": "https://example.test/course", "note": "Optional reinforcement."},
        }
        payload = build_discord_payload(card)
        self.assertEqual(len(payload["embeds"]), 2)
        self.assertIn("https://example.test/course", payload["embeds"][1]["description"])

    def test_weekly_assessment_renders_five_spoiler_answers(self) -> None:
        card = copy.deepcopy(next(card for _, card in all_cards() if card.get("language") == "bilingual"))
        card.update({"stream": "neuroscience", "category": "neuroscience", "language": "en", "review_items": [{"question": f"Question {i}?", "answer": f"Answer {i}"} for i in range(1, 6)]})
        card["content"] = {"en": card["content"]["en"]}
        card["study_plan"] = {
            "course_day": 7, "course_week": 1, "study_duration_minutes": 60,
            "source_id": "book", "source_title": "Book", "source_locator": "No new pages",
            "source_url": "https://example.test/book", "tasks": [{"minutes": 60, "activity": "Assessment", "en": "Answer five questions."}],
            "study_output": {"en": "Keep a concept map."},
            "assessment": {"mode": "self-check", "score_max": 5, "items": [{"course_day": i, "topic": f"Topic {i}", "module": "Week 1", "review_age_days": 7-i} for i in range(1, 6)], "rubric": "One point per mechanism."},
        }
        description = build_discord_payload(card)["embeds"][1]["description"]
        self.assertEqual(description.count("||Answer"), 5)
        self.assertIn("Scoring", description)

    def test_activation_dates_every_day_and_enables_channel(self) -> None:
        from datetime import date
        plan = {
            "status": "draft",
            "sources": {"book": {"sha256": "abc"}},
            "days": [{"course_day": day} for day in range(1, 183)],
        }
        catalog = {"missing_required": [], "sources": {"book": {"sha256": "abc"}}}
        channels = {"streams": {"neuroscience": {"enabled": False}}}
        activated, configured = prepare_activation(plan, catalog, channels, date(2099, 1, 5))
        self.assertEqual(activated["days"][0]["date"], "2099-01-05")
        self.assertEqual(activated["days"][-1]["date"], "2099-07-05")
        self.assertTrue(configured["streams"]["neuroscience"]["enabled"])

    def test_activation_rejects_non_monday(self) -> None:
        from datetime import date
        with self.assertRaisesRegex(ValueError, "Monday"):
            prepare_activation({"status": "draft", "days": []}, {}, {}, date(2099, 1, 6))

    def test_activation_allows_explicit_midweek_shift(self) -> None:
        from datetime import date
        plan = {"status": "draft", "sources": {"book": {"sha256": "abc"}}, "days": [{"course_day": day} for day in range(1, 183)]}
        catalog = {"missing_required": [], "sources": {"book": {"sha256": "abc"}}}
        channels = {"streams": {"neuroscience": {"enabled": False}}}
        activated, configured = prepare_activation(plan, catalog, channels, date(2099, 1, 6), allow_midweek=True)
        self.assertEqual(activated["days"][0]["date"], "2099-01-06")
        self.assertTrue(configured["streams"]["neuroscience"]["enabled"])

    def test_active_plan_supplies_next_fourteen_generation_slots(self) -> None:
        from datetime import date, timedelta
        start = date(2099, 1, 5)
        days = []
        for offset in range(182):
            days.append({
                "course_day": offset + 1,
                "course_week": offset // 7 + 1,
                "date": (start + timedelta(days=offset)).isoformat(),
                "difficulty": "beginner" if offset < 56 else "intermediate",
                "module": "Foundations",
                "day_type": "concept",
                "topic": f"Topic {offset + 1}",
                "study_duration_minutes": 60,
                "source_id": "book",
                "source_title": "Book",
                "source_locator": "PDF pages 1–2",
                "source_url": "https://example.test/book",
                "source_section_number": 1,
                "tasks": [{"minutes": 60, "activity": "Study", "en": "Study.", "my": "လေ့လာပါ။"}],
                "study_output": {"en": "Explain.", "my": "ရှင်းပြပါ။"},
            })
        with tempfile.TemporaryDirectory() as directory:
            plan_path = Path(directory) / "plan.json"
            plan_path.write_text(json.dumps({"status": "active", "days": days}), encoding="utf-8")
            channels = {"neuroscience": {"categories": ["neuroscience"], "buffer_target": 14, "progression": {"beginner_through": 56, "intermediate_through": 140}}}
            with patch.object(generate_prompt, "NEUROSCIENCE_PLAN", plan_path), patch.object(generate_prompt, "load_channels", return_value=channels), patch.object(generate_prompt, "all_cards", return_value=[]):
                slots = generate_prompt.missing_slots(today=start)
        self.assertEqual(len(slots), 14)
        self.assertEqual(slots[0]["sequence"], 1)
        self.assertEqual(slots[-1]["sequence"], 14)
        self.assertEqual(slots[0]["study_plan"]["study_duration_minutes"], 60)

    def test_source_material_uses_only_assigned_pdf_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            cache = temporary_root / "book.json"
            cache.write_text(json.dumps({"sections": [{
                "number": 1,
                "text": "[Page 1]\nfirst\n[Page 2]\nsecond\n[Page 3]\nthird",
            }]}), encoding="utf-8")
            catalog = temporary_root / "catalog.json"
            catalog.write_text(json.dumps({"sources": {"book": {"sha256": "abc", "cache_file": "book.json"}}}), encoding="utf-8")
            plan_path = temporary_root / "plan.json"
            plan_path.write_text(json.dumps({"sources": {"book": {"sha256": "abc"}}}), encoding="utf-8")
            slots = [{
                "stream": "neuroscience",
                "date": "2099-01-05",
                "source_section_number": 1,
                "study_plan": {"source_id": "book", "source_title": "Book", "source_locator": "PDF pages 2–2"},
            }]
            with patch.object(generate_prompt, "ROOT", temporary_root), patch.object(generate_prompt, "NEUROSCIENCE_CATALOG", catalog), patch.object(generate_prompt, "NEUROSCIENCE_PLAN", plan_path):
                material = generate_prompt.neuroscience_source_material(slots)
        self.assertIn("second", material[0]["excerpt"])
        self.assertNotIn("first", material[0]["excerpt"])
        self.assertNotIn("third", material[0]["excerpt"])

    def test_validator_rejects_study_plan_shorter_than_one_hour(self) -> None:
        card = copy.deepcopy(next(card for _, card in all_cards() if card.get("language") == "bilingual"))
        card.update({
            "id": "neuroscience-duration-test-001",
            "stream": "neuroscience",
            "category": "neuroscience",
            "sequence": 1,
            "date": "2099-01-05",
            "difficulty": "beginner",
            "study_plan": {
                "course_day": 1,
                "course_week": 1,
                "study_duration_minutes": 60,
                "source_id": "brain-facts-2018",
                "source_title": "Brain Facts",
                "source_locator": "PDF pages 1–5",
                "tasks": [{"minutes": 59, "activity": "Study", "en": "Read carefully.", "my": "သေချာဖတ်ပါ။"}],
                "study_output": {"en": "Draw one diagram.", "my": "Diagram တစ်ခု ဆွဲပါ။"},
            },
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "card.json"
            path.write_text(json.dumps(card), encoding="utf-8")
            errors = validate([path])
        self.assertTrue(any("task minutes total 59" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

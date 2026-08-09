from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generation_runner import (
    GenerationJob,
    build_jobs,
    output_schema,
    run_job,
    strip_nullable_fields,
    validate_job_cards,
)


class GenerationRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.channels = {
            "linux": {"categories": ["linux", "networking"]},
            "ai": {"categories": ["ai", "ai-engineering"]},
        }
        self.slots = [
            {
                "stream": "linux",
                "date": f"2099-01-{day:02d}",
                "sequence": day,
                "required_difficulty": "beginner",
                "suggested_category": "linux",
            }
            for day in range(1, 6)
        ]

    def test_jobs_are_batched_per_stream(self) -> None:
        jobs = build_jobs(self.slots, batch_size=2)
        self.assertEqual([len(job.slots) for job in jobs], [2, 2, 1])
        self.assertTrue(all(job.stream == "linux" for job in jobs))

    def test_output_schema_is_strict_at_every_object_level(self) -> None:
        schema = output_schema(2)
        self.assertFalse(schema["additionalProperties"])
        cards = schema["properties"]["cards"]
        self.assertEqual(cards["minItems"], 2)
        self.assertEqual(cards["maxItems"], 2)
        card = cards["items"]
        self.assertFalse(card["additionalProperties"])
        self.assertEqual(set(card["required"]), set(card["properties"]))
        content = card["properties"]["content"]
        self.assertFalse(content["additionalProperties"])
        self.assertFalse(content["properties"]["en"]["additionalProperties"])

    def test_nullable_placeholders_are_removed(self) -> None:
        card = {
            "command": None,
            "flags": [{"flag": "-a", "meaning": None, "en": "all", "my": None}],
            "review_items": None,
        }
        cleaned = strip_nullable_fields(card)
        self.assertNotIn("command", cleaned)
        self.assertNotIn("review_items", cleaned)
        self.assertEqual(cleaned["flags"], [{"flag": "-a", "en": "all"}])

    def test_slot_contract_rejects_wrong_progression(self) -> None:
        job = GenerationJob("linux-test", "linux", (self.slots[0],))
        card = {
            "stream": "linux",
            "date": "2099-01-01",
            "sequence": 1,
            "difficulty": "advanced",
            "category": "linux",
            "status": "approved",
        }
        errors = validate_job_cards([card], job, self.channels)
        self.assertTrue(any("difficulty beginner" in error for error in errors))

    def test_slot_contract_accepts_review_cross_category(self) -> None:
        job = GenerationJob("linux-test", "linux", (self.slots[0],))
        card = {
            "stream": "linux",
            "date": "2099-01-01",
            "sequence": 1,
            "difficulty": "beginner",
            "category": "review",
            "status": "approved",
        }
        self.assertEqual(validate_job_cards([card], job, self.channels), [])

    def test_failed_codex_job_changes_only_ignored_cache(self) -> None:
        job = GenerationJob("linux-failure-test", "linux", (self.slots[0],))
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fake_codex = temporary / "fake-codex"
            fake_codex.write_text("#!/usr/bin/env bash\nexit 7\n", encoding="utf-8")
            fake_codex.chmod(0o755)
            result = run_job(
                job,
                ROOT,
                temporary / "cache",
                timeout_seconds=5,
                channels=self.channels,
                codex_command=str(fake_codex),
            )
            self.assertIsNone(result.cards)
            self.assertIn("status 7", result.error or "")
            self.assertFalse(any((ROOT / "cards").rglob("*failure-test*")))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ai_review_and_schedule import schedule_complete_rows
from cardlib import RICH_REQUIRED, all_cards, build_discord_payload
from validate_cards import validate


class TeachingCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cards = [card for _, card in all_cards()]

    def test_every_bilingual_card_uses_teaching_schema(self) -> None:
        for card in self.cards:
            if card.get("language") != "bilingual":
                continue
            for language in ("en", "my"):
                block = card["content"][language]
                self.assertTrue(RICH_REQUIRED <= block.keys(), card["id"])
                self.assertNotIn("summary", block, card["id"])
                self.assertNotIn("explanation", block, card["id"])

    def test_visuals_and_discord_payloads_fit_safe_limits(self) -> None:
        for card in self.cards:
            if card.get("language") != "bilingual":
                continue
            for language in ("en", "my"):
                self.assertLessEqual(max(map(len, card["content"][language]["visual"].splitlines())), 48, card["id"])
            payload = build_discord_payload(card)
            descriptions = [embed["description"] for embed in payload["embeds"]]
            self.assertTrue(all(len(description) <= 2700 for description in descriptions), card["id"])
            total = sum(len(embed.get("title", "")) + len(embed.get("description", "")) + len(embed.get("footer", {}).get("text", "")) for embed in payload["embeds"])
            self.assertLessEqual(total, 5800, card["id"])

    def test_validator_rejects_summary_schema_and_wide_visual(self) -> None:
        card = copy.deepcopy(self.cards[0])
        block = card["content"]["en"]
        block["summary"] = block.pop("learning_objective")
        block["visual"] = "x" * 49
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(card), encoding="utf-8")
            errors = validate([path])
        self.assertTrue(any("learning_objective" in error for error in errors))
        self.assertTrue(any("wider than 48" in error for error in errors))

    def test_rejected_cards_cannot_form_a_scheduling_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index, stream in enumerate(("linux", "ai", "dev", "mlops"), 1):
                card = copy.deepcopy(self.cards[0])
                card.update({"id": f"rejected-test-{stream}", "stream": stream, "status": "rejected", "date": None, "sequence": None})
                path = Path(directory) / f"{index}.json"
                path.write_text(json.dumps(card), encoding="utf-8")
                paths.append(path)
            self.assertEqual(schedule_complete_rows(paths, date(2099, 1, 1)), 0)


if __name__ == "__main__":
    unittest.main()

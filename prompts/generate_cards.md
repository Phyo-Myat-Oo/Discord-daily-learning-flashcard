# Curriculum card generation

You are replenishing a file-based daily technical-learning curriculum. Read `AGENTS.md` first and obey it.

The dynamic context appears below this template. Create exactly the requested number of cards, one for each listed date, under the category directories in `cards/`. Do not overwrite files. Each card must be approved, atomic, practical, accurate JSON matching `cards/schema.json`, and comfortably under Discord's limit when rendered. Prefer meaningful operational knowledge over trivia. Inspect all existing cards and `state/topics.json` before choosing topics; revisit a topic only for a clearly different advanced skill.

Follow the date rotation as a quality-oriented guide. Update `state/topics.json` for every new curriculum card. Do not change scripts, prompts, workflows, documentation, systemd files, source files, imported cards, or existing cards. Run `python scripts/validate_cards.py` and fix only the cards/state you just created until it passes.


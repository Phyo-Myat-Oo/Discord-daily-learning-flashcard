# Daily Learning agent instructions

This repository delivers one pre-generated technical flashcard per day through GitHub Actions and a Discord webhook. No LLM runs in GitHub Actions.

## Card-generation scope

During curriculum generation, modify only new files below `cards/<category>/` and `state/topics.json`. During source ingestion, modify only the explicitly assigned new directory below `cards/imported/`; the ingestion script owns `state/imports.json`. Never edit existing cards, original sources, scripts, prompts, workflows, systemd units, or documentation unless the user explicitly requests project maintenance.

## Quality and schema

- Follow `cards/schema.json`; store one JSON object per card and one atomic concept per card.
- Every card has a `stream` from `config/channels.json`. Its category must be allowed by that stream. Dates are unique within a stream, so different streams may each have a card on the same day.
- Every card needs one useful explanation, one realistic example, one real-world use case, and one active-recall question/answer.
- New cards use `language: bilingual` with complete `content.en` and `content.my` blocks. Draft and verify English first, then express the same meaning in natural Burmese rather than translating word-for-word. Keep commands, code, flags, filenames, standard acronyms, and technical terms in their accurate original form when translation would reduce clarity. Legacy `language: my` cards remain valid during migration.
- A bilingual card is a structured mini-lesson, not a summary. It must state one observable learning objective, introduce the idea concretely, explain the cause-and-effect mechanism, walk through a realistic example, state the expected result, tell the learner what to notice, identify a genuine mistake, give one practical tip, and finish with one aligned recall question.
- Write for comprehension before compression. Define unfamiliar terms before using them, prefer short cause-and-effect sentences, connect abstract ideas to a concrete situation, and explain what the learner should notice in the example. Do not assume that naming a component explains it.
- Follow `state/terminology.json`. Write Burmese as an independent explanation by a patient technical instructor, not as a word-for-word translation. Retain familiar English technical terms when clearer, explain them naturally at first use, and keep terminology consistent.
- Every rich language block includes one compact `visual`. Use a text flow, state transition, hierarchy, side-by-side comparison, or annotated command only when it directly clarifies the concept. Keep it readable on a phone (normally 2–6 short lines and never more than 48 characters on one line), use box-drawing characters and arrows consistently, and never use decorative diagrams that add no information. Prefer vertical layouts when a horizontal flow would be wide. Burmese visuals may retain standard English technical labels when clearer.
- Source-based curriculum cards use a stable `concept_key`, `track`, and `track_sequence`. Progress each subject independently even when several subjects share one Discord stream.
- Use categories: linux, networking, git, docker, python, ai, mlops, ai-engineering, neuroscience, or review. Difficulty is beginner, intermediate, or advanced.
- Curriculum cards are `approved` and dated. Each configured stream maintains its own future buffer. Source-derived cards are initially `candidate`, normally undated, include a valid stream, reliable source metadata, `generated_from_source: true`, and a priority.
- Sunday review cards use `category: review` plus at least two atomic `review_items`, each containing a question and answer. Keep the normal recall fields as a concise description/fallback.
- Neuroscience curriculum cards are English-only (`language: en`, `content.en` only) and are the exception to generic Sunday review cards: they retain `category: neuroscience` and follow the locked 182-day course plan. Copy `study_plan` exactly, keep its required tasks at 60 minutes total, use only its assigned source excerpt, and never add required pages or work. Preserve the curated optional online-resource link. The lesson must fit beside the study-plan embed.
- Respect neuroscience workload metadata: never expand its adaptive page range or change its 18–30 minute source-study time box. When an assessment blueprint is present, generate exactly five mechanism-focused `review_items` in blueprint order with concise spoiler-safe answers; do not request user tracking or shift the fixed calendar.
- Keep each language comfortably inside one Discord embed and keep combined embed text below Discord's aggregate limit. Never turn a card into a giant tutorial.
- Prefer practical operational knowledge. Avoid trivia and repetitive basics.
- Inspect every card and `state/topics.json` before writing. Do not duplicate an equivalent question; a repeated topic must teach a meaningfully different application or deeper skill.
- Infer a few consistent, useful tags rather than inventing many near-synonyms.

## Source fidelity

Understand the supplied material before selecting high-value knowledge. Preserve source grounding and references that can be determined reliably. Never fabricate page, section, cell, claim, or result. If uncertain, set `needs_review: true`; distinguish source claims from additional explanation. Never modify or copy the source into the repository.

## Safety and privacy

Never create malicious, credential-stealing, or casually destructive instructions. Commands such as `rm`, `dd`, `mkfs`, recursive permission changes, `docker system prune`, and `git reset --hard` require an explicit description of effects, risk, safer inspection/dry-run steps, and recovery limitations. Prefer non-destructive demonstrations.

Never include passwords, API keys, tokens, private keys, sensitive environment values, or private notebook output in a card. Run `python scripts/validate_cards.py` and fix newly created content until validation passes.

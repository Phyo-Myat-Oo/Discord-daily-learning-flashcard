# Source-derived candidate generation

Read `AGENTS.md` first. Analyze the normalized source referenced in the dynamic context. Select the highest-value knowledge for active recall; do not merely summarize or convert every paragraph/cell. Generate no more than the card budget, and fewer when the source does not support enough excellent atomic cards.

Write separate JSON card files only inside the exact output directory. Each must match `cards/schema.json`, use `language: my`, write all learning prose naturally in Burmese while preserving commands/code/flags/technical terms where clearer, use `status: candidate`, be undated, choose the best fitting configured `stream` and one of its allowed categories, set `generated_from_source: true`, include the supplied `source_type`, `source_file`, and priority, and retain only source section/page/cell metadata that is directly supported by markers in the normalized text. Do not invent references or claims. Set `needs_review: true` when grounding is uncertain. Inspect existing cards and topic history to avoid equivalent questions. Never modify the source or any other repository file.

Depth meaning: quick selects only central ideas; normal balances central concepts and implementation knowledge; deep adds justified detail without sacrificing atomicity. Run validation on your output directory and correct your new files until it passes.

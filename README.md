# Daily Learning Flashcards

A file-based system that sends different practical technical flashcards to multiple Discord channels every day. Codex occasionally generates a 14-day buffer for each configured stream on your Ubuntu computer; GitHub Actions only validates and sends already-generated JSON. There is no VPS, always-running bot, database, or LLM in CI.

```text
Ubuntu + systemd → Codex batch → JSON validation → Git push
                                                     ↓
Discord webhooks ← daily GitHub Action ← dated approved cards per stream

Local PDF/notebook/notes → extractor → Codex candidates → manual approval/scheduling
```

## Project structure

```text
cards/                 curriculum categories, imported candidates, and schema
config/channels.json   streams, allowed categories, buffer targets, secret names
prompts/               curriculum and source-analysis Codex prompts
scripts/               validation, sending, generation, import, and review tools
sources/               ignored inbox/processed/failed source locations
state/                 topic and source-hash history
systemd/               user service and timer templates
.github/workflows/     deterministic daily Discord delivery
```

## 1. Install on Ubuntu

Clone the repository at `~/daily-learning` (the supplied systemd units use that path), then:

```bash
cd ~/daily-learning
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
chmod +x scripts/generate.sh scripts/*.py
python3 scripts/validate_cards.py
```

PDF extraction prefers `pypdf` for document outlines and falls back to Ubuntu's `pdftotext` from `poppler-utils`. EPUB and daily delivery use Python's standard library. Install and authenticate the Codex CLI, then verify `codex exec --help` works. Curriculum generation uses ephemeral, read-only Codex sessions that return schema-constrained card data; Python validates and installs it. Codex never receives Git push responsibility.

Configure Git once if needed:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git remote -v
git push
```

Use an SSH remote or a credential helper so unattended `git pull` and `git push` can authenticate. The working tree must be clean before automated generation; review any local edits first.

## 2. Create the Discord webhooks

Create the Discord text channels you want, then open **Server Settings → Integrations → Webhooks → New Webhook** and create one webhook for each enabled channel:

| Stream | Suggested channel | GitHub secret |
|---|---|---|
| `linux` | `#daily-linux` | `DISCORD_WEBHOOK_LINUX` |
| `ai` | `#daily-ai` | `DISCORD_WEBHOOK_AI` |
| `dev` | `#daily-dev` | `DISCORD_WEBHOOK_DEV` |
| `mlops` | `#daily-mlops` | `DISCORD_WEBHOOK_MLOPS` |
| `neuroscience` | `#daily-neuroscience` | `DISCORD_WEBHOOK_NEUROSCIENCE` |

Copy each webhook URL separately. Do not put URLs in a file or commit them. Stream behavior lives in `config/channels.json`; `webhook_env` stores only the environment-variable name.

For a one-off local send test only:

```bash
export DISCORD_WEBHOOK_LINUX='paste-the-linux-webhook-url-here'
python3 scripts/send_discord.py --date 2026-08-10 --stream linux
unset DISCORD_WEBHOOK_LINUX
```

First use `--dry-run` so nothing is posted:

```bash
python3 scripts/send_discord.py --date 2026-08-10 --stream linux --dry-run
python3 scripts/send_discord.py --today --all --dry-run
```

## 3. Configure GitHub

Push this project to GitHub. In **Repository Settings → Secrets and variables → Actions**, add the secrets for every enabled stream. The neuroscience stream ships disabled until its source-grounded plan and initial cards are ready. The workflow runs at 00:15 Asia/Yangon (17:45 UTC), validates all cards, locates one card for each `(stream, Yangon date)`, preflights every enabled stream, and then posts each card to its webhook. A missing card or secret fails before any message is sent.

Under **Actions → Send daily learning card → Run workflow**, optionally enter a sample date such as `2026-08-10`. This performs a real post. GitHub may delay scheduled workflows during load, but date lookup remains based on Asia/Yangon.

## 4. Curriculum buffer and local generation

```bash
python3 scripts/card_status.py
python3 scripts/validate_cards.py
./scripts/generate.sh
```

`generate.sh` pulls with `--ff-only`, calculates missing `(stream, date)` slots up to each stream's configured 14-card future buffer, and invokes Codex in resumable two-card jobs. Two jobs run concurrently by default. Codex returns structured JSON into ignored local staging; Python validates each job against existing cards, validates the combined batch, installs it, and updates `state/topics.json` deterministically. The shell then stages only `cards/` plus `state/topics.json`, commits, and pushes. A failed run changes no tracked files and retains successful outputs for the next retry. When every stream is full, it exits without invoking Codex. Read `AGENTS.md` to see the permanent quality, scope, duplication, and safety rules.

Preview the next generation plan without calling Codex:

```bash
python3 scripts/generation_runner.py --plan
```

The safe defaults can be overridden for troubleshooting or a faster connection:

```bash
CODEX_GENERATION_CONCURRENCY=2 \
CODEX_GENERATION_BATCH_SIZE=2 \
CODEX_TIMEOUT_SECONDS=900 \
CODEX_GENERATION_RETRIES=1 \
./scripts/generate.sh
```

The runner prints a heartbeat every 30 seconds. Override that interval with `CODEX_HEARTBEAT_SECONDS` if needed. Higher concurrency reduces wall-clock time but may encounter account or network rate limits.

To add a card manually, copy a nearby JSON file into the correct category, choose a unique ID and unused ISO date, update `state/topics.json`, then run validation and a dry-run preview. Scheduled cards require dates; approved imported cards may remain undated until you place them in the delivery calendar.

## 5. Prepare the six-month neuroscience course

The neuroscience stream is a locked 182-day BCI and neuroengineering course. Its cards are English-only. Every Discord message contains a teaching-focused lesson and an exact 60-minute assignment, plus clickable links to the assigned book source and one curated free online companion. The online companion is optional and does not increase the required study time. Its weekly rhythm is five concept days, one practical day, and one lighter review day.

Reading ranges are allocated by extracted workload rather than page count alone. The scanner measures words, equation-like lines, figure/table references, and code, then the plan gives dense pages smaller ranges and adjusts source-study time between 18 and 30 minutes while keeping the entire session at 60 minutes. Sundays contain five spoiler-answer self-check questions: three from the current week plus increasingly spaced earlier concepts. The calendar never pauses or shifts based on the self-score.

Online companions are configured in `config/neuroscience_online_resources.json`. Check their availability locally when desired (network failures do not block daily GitHub Actions):

```bash
python scripts/check_neuroscience_links.py
```

Obtain these exact resources legally and place PDF or EPUB files in a private local directory such as `~/Downloads/pdf_daily/neuroscience/`:

- *Brain Facts: A Primer on the Brain and Nervous System* — [free official PDF](https://www.sfn.org/-/media/Brainfacts2/BrainFacts-Book/Brain-Facts-Book-2018-high-res.pdf)
- *Neuroscience: Exploring the Brain, Fourth Edition* — [publisher](https://www.jblearning.com/catalog/productdetails/9780781778176)
- *Neuronal Dynamics* — [official online book](https://neuronaldynamics.epfl.ch/online/)
- *Analyzing Neural Time Series Data: Theory and Practice* — [MIT Press](https://mitpress.mit.edu/9780262019873/analyzing-neural-time-series-data/)
- *Brain–Computer Interfaces: Principles and Practice* — [Oxford Academic](https://academic.oup.com/book/1700)

PDFs receive exact page ranges. EPUBs receive stable chapter/section locators because EPUB page numbers vary by reader. The scanner is non-recursive, accepts at most 20 files, keeps extracted text under ignored `.generated/`, and reports unrecognized or missing books:

```bash
mkdir -p ~/Downloads/pdf_daily/neuroscience
python3 scripts/neuroscience_sources.py scan \
  ~/Downloads/pdf_daily/neuroscience
python3 scripts/neuroscience_sources.py status
```

Build and inspect the full course without enabling Discord:

```bash
python3 scripts/build_neuroscience_plan.py
python3 scripts/neuroscience_status.py --next 14
```

Before activation, create `#daily-neuroscience` and add `DISCORD_WEBHOOK_NEUROSCIENCE` to GitHub Actions secrets. Activation defaults to the next Monday. To deliberately shift the complete seven-day learning cycle, an explicit non-Monday date requires `--allow-midweek`:

```bash
python3 scripts/activate_neuroscience_plan.py
# or: python3 scripts/activate_neuroscience_plan.py --start-date 2026-08-17
# shifted cycle: python3 scripts/activate_neuroscience_plan.py --start-date 2026-08-11 --allow-midweek
```

Activation changes tracked plan/configuration files. Generate the initial 14-card buffer directly before committing, so GitHub never sees an enabled but empty stream:

```bash
python3 scripts/generation_runner.py --plan
python3 scripts/generation_runner.py --stream neuroscience
python3 scripts/validate_cards.py
python3 scripts/neuroscience_status.py --next 14
python3 scripts/send_discord.py --stream neuroscience --date YYYY-MM-DD --dry-run
git add config cards state README.md AGENTS.md scripts prompts .github
git commit -m "feat: add daily neuroscience course"
git push
```

After initial activation, the normal systemd-driven `generate.sh` replenishes neuroscience together with the other streams. If a source file changes, generation stops until you rescan and rebuild rather than silently using incorrect pages.

## 6. Enable the user systemd timer

No root access is required:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/daily-learning-generate.service ~/.config/systemd/user/
cp systemd/daily-learning-generate.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now daily-learning-generate.timer
systemctl --user status daily-learning-generate.timer
systemctl --user list-timers
```

The timer runs Monday and Thursday mornings with a small randomized delay. `Persistent=true` catches a missed run after the computer next starts and the user manager is available. Test immediately with:

```bash
systemctl --user start daily-learning-generate.service
journalctl --user -u daily-learning-generate.service -n 100
```

If this repository is elsewhere, edit both `WorkingDirectory` and `ExecStart` in the installed service. For timers to run before login, Ubuntu can optionally enable user lingering with `loginctl enable-linger "$USER"`; this is not necessary if catching up after login is sufficient.

## 7. Import private/local study sources

Supported: PDF, EPUB, Jupyter notebook, Markdown, text, and Python. Extraction is separate from generation. Use only sources you are legally permitted to process. Keep purchased/private books outside this repository and never commit them.

The extractor preserves reading order and emits bounded sections rather than passing an entire book to Codex. PDF outlines become sections when `pypdf` exposes them; otherwise the Ubuntu fallback creates safe page windows. Recurring headers and footers are removed, split words are repaired, and page locators remain visible. EPUB follows its spine and removes markup, scripts, styles, and non-reading assets. Notebooks are grouped by headings while metadata, images, widgets, large outputs, and execution counters are omitted.

Inspect detected sections before generating anything:

```bash
python3 scripts/import_source.py ~/Books/LinuxCommand.pdf --list-sections
python3 scripts/import_source.py ~/Books/book.epub --list-sections
```

Then import one coherent chapter or a small group. `--section` accepts a 1-based number or case-insensitive title fragment and may be repeated:

```bash
python3 scripts/import_source.py ~/Books/LinuxCommand.pdf --section 2 --depth normal --max-cards 8
python3 scripts/import_source.py ~/Books/book.epub --section "Data Model" --max-cards 10
python3 scripts/import_source.py lecture.ipynb --depth deep --max-cards 30 --priority high
python3 scripts/import_source.py sources/inbox/ --max-files 20
python3 scripts/review_cards.py
python3 scripts/import_status.py
```

Directories are deliberately non-recursive and capped. Normalized text is limited by `--max-source-chars` (120,000 by default), placed in ignored `.generated/`, and never staged by `generate.sh`. Original sources remain where they are. SHA-256 plus the selected section set prevents accidental repeat imports while allowing different chapters and changed revisions.

New candidates are comprehension-first bilingual mini-lessons rather than summaries. Each language states one learning objective, introduces the idea concretely, explains cause and effect, provides a narrow mental-model visual, walks through an observable example, and separates the expected result from what the learner should notice. A mistake, practical tip, and aligned recall question complete the lesson. English is drafted first; Burmese is written independently in a patient technical-instructor voice using the shared terminology guide in `state/terminology.json`. Discord sends the two languages as equal-depth embeds while legacy Burmese-only cards remain supported.

To remove manual approval, pass candidate directories from every configured stream through the AI review gate. The command invokes a separate Codex review, validates its corrections, and schedules only complete dates containing one card for every stream:

```bash
python3 scripts/ai_review_and_schedule.py \
  cards/imported/linux-batch \
  cards/imported/ai-batch \
  cards/imported/dev-batch \
  cards/imported/mlops-batch
```

If AI review times out, rejects a card, validation fails, or a complete all-stream row is unavailable, nothing incomplete is scheduled. Each review run uses a unique nonce that Codex must write into every passing card, so a successful but no-op Codex process fails closed instead of silently scheduling unreviewed content. Post-scheduling validation is transactional: edited candidates are restored if the full repository fails validation.

Candidates live in `cards/imported/<source-slug-hash>/` with `status: candidate`. Edit JSON freely, then approve without scheduling or approve and distribute cards across unused dates:

```bash
python3 scripts/approve_cards.py cards/imported/example-ab12cd34/
python3 scripts/approve_cards.py cards/imported/example-ab12cd34/ --schedule --spacing-days 3
```

The spaced option avoids delivering one paper's cards consecutively. Priority is visible during review and available to future schedulers; V1 keeps scheduling explicit and understandable rather than silently reshuffling existing dates.

After review, commit only the intended candidate cards and `state/imports.json`; inspect `git diff --staged` before pushing. Never add ignored source or `.generated/` content.

Imported material may be private. Only candidate JSON and import history are candidates for Git; source and extracted files are ignored. Validation scans cards for common secret/key/password patterns and fails for manual review, but no pattern scanner is perfect—read imported cards before committing.

## Troubleshooting

- **No card today:** run `python3 scripts/card_status.py`; create/schedule the missing `(stream, date)`, validate, commit, and push. The Action intentionally sends nothing if preflight fails.
- **Codex creates nothing:** inspect `.generated/curriculum/*/jobs/*/codex.log`, confirm Codex authentication, and run `python3 scripts/generation_runner.py --plan`. Valid completed jobs are reused automatically on retry.
- **PDF has no text:** it is probably scanned; OCR it outside this project and import the resulting text/PDF.
- **Neuroscience plan will not build:** run `python3 scripts/neuroscience_sources.py status`; provide every required exact edition and rescan. The builder intentionally refuses guessed locators.
- **Timer fails:** inspect `journalctl --user -u daily-learning-generate.service`; verify the repo path, executable bit, network, Codex login, and Git credentials.
- **Push is rejected:** manually reconcile remote changes; automation intentionally uses only `git pull --ff-only`.
- **Discord HTTP error:** verify the corresponding stream's Actions secret and webhook channel permissions. Never print the secret.
- **Validation fails after approval:** fix the reported card before committing. Approval does not bypass safety, duplicate, date, or message-size checks.

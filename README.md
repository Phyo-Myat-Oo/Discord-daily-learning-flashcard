# Daily Learning Flashcards

A file-based system that sends one practical technical flashcard to Discord every day. Codex occasionally generates a 14-day buffer on your Ubuntu computer; GitHub Actions only validates and sends already-generated JSON. There is no VPS, always-running bot, database, or LLM in CI.

```text
Ubuntu + systemd → Codex batch → JSON validation → Git push
                                                     ↓
Discord webhook ← daily GitHub Action ← dated approved cards

Local PDF/notebook/notes → extractor → Codex candidates → manual approval/scheduling
```

## Project structure

```text
cards/                 curriculum categories, imported candidates, and schema
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

Only PDF extraction needs the `pypdf` dependency; the daily sender uses Python's standard library. Install and authenticate the Codex CLI, then verify `codex exec --help` works. The generation scripts use an ephemeral, workspace-write session rooted at this repository. They never give Codex Git push responsibility.

Configure Git once if needed:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git remote -v
git push
```

Use an SSH remote or a credential helper so unattended `git pull` and `git push` can authenticate. The working tree must be clean before automated generation; review any local edits first.

## 2. Create the Discord webhook

In Discord, open **Server Settings → Integrations → Webhooks → New Webhook**, choose `#daily-learning`, and copy its URL. Do not put it in a file or commit it.

For a one-off local send test only:

```bash
export DISCORD_WEBHOOK_URL='paste-the-webhook-url-here'
python3 scripts/send_discord.py --date 2026-08-10
unset DISCORD_WEBHOOK_URL
```

First use `--dry-run` so nothing is posted:

```bash
python3 scripts/send_discord.py --date 2026-08-10 --dry-run
python3 scripts/send_discord.py --today --dry-run
```

## 3. Configure GitHub

Push this project to GitHub. In **Repository Settings → Secrets and variables → Actions**, add a repository secret named `DISCORD_WEBHOOK_URL`. The workflow runs at 00:15 Asia/Yangon (17:45 UTC), validates all cards, locates the current Yangon date, and posts exactly one approved/scheduled card. Missing or duplicate dates fail with a useful log and send nothing.

Under **Actions → Send daily learning card → Run workflow**, optionally enter a sample date such as `2026-08-10`. This performs a real post. GitHub may delay scheduled workflows during load, but date lookup remains based on Asia/Yangon.

## 4. Curriculum buffer and local generation

```bash
python3 scripts/card_status.py
python3 scripts/validate_cards.py
./scripts/generate.sh
```

`generate.sh` pulls with `--ff-only`, calculates missing dates up to a 14-card future buffer, passes dynamic context to Codex, validates, stages only `cards/` plus `state/topics.json`, commits, and pushes. If 14 future cards already exist, it exits without invoking Codex. Read `AGENTS.md` to see the permanent quality, scope, duplication, and safety rules.

To add a card manually, copy a nearby JSON file into the correct category, choose a unique ID and unused ISO date, update `state/topics.json`, then run validation and a dry-run preview. Scheduled cards require dates; approved imported cards may remain undated until you place them in the delivery calendar.

## 5. Enable the user systemd timer

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

## 6. Import private/local study sources

Supported in version 1: PDF, Jupyter notebook, Markdown, text, and Python. Extraction is separate from generation. Notebook metadata, images, widgets, large outputs, and execution counters are omitted. PDFs retain explicit page markers when text extraction succeeds.

```bash
python3 scripts/import_source.py ~/papers/paper.pdf --depth quick --max-cards 8
python3 scripts/import_source.py lecture.ipynb --depth deep --max-cards 30 --priority high
python3 scripts/import_source.py sources/inbox/ --max-files 20
python3 scripts/review_cards.py
python3 scripts/import_status.py
```

Directories are deliberately non-recursive and capped. Normalized text is placed in ignored `.generated/`; original sources remain where they are and are never staged by `generate.sh`. A SHA-256 history in `state/imports.json` prevents reprocessing identical content while allowing changed revisions.

Candidates live in `cards/imported/<source-slug-hash>/` with `status: candidate`. Edit JSON freely, then approve without scheduling or approve and distribute cards across unused dates:

```bash
python3 scripts/approve_cards.py cards/imported/example-ab12cd34/
python3 scripts/approve_cards.py cards/imported/example-ab12cd34/ --schedule --spacing-days 3
```

The spaced option avoids delivering one paper's cards consecutively. Priority is visible during review and available to future schedulers; V1 keeps scheduling explicit and understandable rather than silently reshuffling existing dates.

After review, commit only the intended candidate cards and `state/imports.json`; inspect `git diff --staged` before pushing. Never add ignored source or `.generated/` content.

Imported material may be private. Only candidate JSON and import history are candidates for Git; source and extracted files are ignored. Validation scans cards for common secret/key/password patterns and fails for manual review, but no pattern scanner is perfect—read imported cards before committing.

## Troubleshooting

- **No card today:** run `python3 scripts/card_status.py`; create/schedule the missing date, validate, commit, and push. The Action intentionally sends nothing on failure.
- **Codex creates nothing:** inspect the full generation output and confirm authentication plus workspace permissions. Run `python3 scripts/generate_prompt.py` to inspect its prompt.
- **PDF has no text:** it is probably scanned; OCR it outside this project and import the resulting text/PDF.
- **Timer fails:** inspect `journalctl --user -u daily-learning-generate.service`; verify the repo path, executable bit, network, Codex login, and Git credentials.
- **Push is rejected:** manually reconcile remote changes; automation intentionally uses only `git pull --ff-only`.
- **Discord HTTP error:** verify the Actions secret and webhook channel permissions. Never print the secret.
- **Validation fails after approval:** fix the reported card before committing. Approval does not bypass safety, duplicate, date, or message-size checks.

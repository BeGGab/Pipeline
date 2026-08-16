# AI Software Pipeline

Telegram control channel for GitHub Copilot coding agent.

```
/new → Issue → Copilot → PR → Telegram (ссылка)
     → /diff → PR-N.diff → внешнее ревью → при необходимости Copilot fixes
     → /diff → /merge → confirmation → GitHub merge → задача завершена
```

AI-review в MVP нет: комментарий «Pipeline check: CI passed, no automated review configured.»

Целевой репозиторий должен содержать `.github/workflows/` до делегирования агенту, либо агента нужно явно попросить создать минимальный CI (ISSUE-001, не баг пайплайна).

## What it does

1. Authorized user sends `/new <task>` in Telegram.
2. Pipeline opens a GitHub Issue and assigns `copilot-swe-agent[bot]`.
3. GitHub webhooks **and** `watch_issue` polling feed the same `process_event()` path.
4. When a PR exists, `/diff` sends the live unified diff as `PR-{n}.diff`.
5. `/merge` shows CI/PR status and merges only after an explicit button press.

Telegram never calls the GitHub API. GitHub remains the source of truth.

## Requirements

- Python 3.11+
- Telegram bot token
- GitHub token that can create issues, assign Copilot, read PRs/Actions, and merge
- Copilot coding agent enabled on the **target** repository
- CI workflows in the target repository (or ask the agent to add them)

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```

Fill `.env`:

| Variable | Meaning |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_ALLOWED_USER_IDS` | Comma-separated Telegram user IDs. Empty list denies everyone. |
| `GITHUB_TOKEN` | Fine-grained or classic PAT |
| `GITHUB_OWNER` / `GITHUB_REPO` | Target repository |
| `GITHUB_WEBHOOK_SECRET` | Secret for `POST /webhooks/github` |
| `COPILOT_USERNAME` | `copilot-swe-agent[bot]` |
| `JOBS_STORE_PATH` | JSON file for jobs + processed event IDs. Empty = in-memory only. |

Point a GitHub webhook at `https://<host>/webhooks/github` for `issues`, `issue_comment`, `pull_request`, `workflow_run`. Polling still works if the webhook is missing.

```bash
python -m app.main
```

## Commands

| Command | Effect |
| --- | --- |
| `/new <text>` | Create issue, assign Copilot |
| `/diff` | Live unified diff of the current job PR |
| `/merge` | Status + Merge/Cancel buttons |
| `/status` | Current job state |

## Tests

```bash
pytest
```

Covers BUG-001…009, PR-001…PR-013, and process-restart persistence (`TEST-015+`).

## Layout

```
adapters/     GitHub, Telegram, coding agent, file/in-memory jobs
orchestrator/ Job FSM, watchers, /diff, /merge
ports/        Protocols — Telegram does not import GitHub
webhooks/     Signature check → parse_webhook_event
docs/         TZ, architecture, acceptance program
```

## Spec sources

`AI-PIPELINE-PR-FIXES.txt` and `AI-PIPELINE-PR-FIXES.diff` in the repo root are the defect TZ (BUG-001…011) and PIPE-PR-001 (`/diff`, `/merge`) this tree implements.

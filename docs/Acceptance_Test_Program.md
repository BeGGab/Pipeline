# Acceptance Test Program

A point is closed when the “problem” scenario no longer reproduces and the “criterion” scenario does.

## TEST-001 Webhook off, polling finishes the job (BUG-001)

Disable the repository webhook or break the secret. `/new` still reaches a final Telegram message via `watch_issue`.

## TEST-002 Stale warning (BUG-001)

A job left in `CODING_AGENT_RUNNING` / `WAIT_TESTS` past `CODING_AGENT_STALE_TIMEOUT_SEC` produces a warning and does **not** become `FAILED`.

## TEST-003 Fix command (BUG-002 / BUG-003 / FR-4.2)

On CI failure the issue comment starts with exactly `@copilot Fix the failing tests`. `grep -rn trigger_fix_iteration` shows the orchestrator call. `github.trigger_fix` does not exist.

## TEST-004 Agent login (BUG-004 / BUG-007)

`grep -rn "github-copilot\[bot\]"` is empty except the explicit “erroneous assumption” note. Comments from `copilot-pull-request-reviewer[bot]` do not create `AGENT_STARTED` / `COPILOT_QUESTION` / `AGENT_COMPLETED`.

## TEST-005 Assignment fact (BUG-005)

Repository with Copilot coding agent disabled (or a token without rights) → `ADAPTER_ERROR`, not a fake “agent started”.

## TEST-006 Completion signal (BUG-006)

`draft=false` and/or requested reviewers produce completion even without a magic comment.

## TEST-007 Completed Actions run (BUG-008)

`get_latest_run_for_branch` with an `in_progress` run on top of a previous `failure` returns the completed failure.

## TEST-008 Honest review comment (BUG-009)

Bot text does not claim an AI review that was not performed.

## TEST-015+ PR review control (PIPE-PR-001)

| ID | Criterion |
| --- | --- |
| PR-001 | Open PR, `/diff` → GitHub queried, file sent, PR unchanged |
| PR-002 | New commit, second `/diff` → fresh diff |
| PR-003 | `/merge` with CI PASS → confirmation only, no merge yet |
| PR-004 | Confirm + GitHub allows → merge, job `DONE` |
| PR-005 | CI FAILURE → no merge |
| PR-006 | CI running → no merge |
| PR-007 | Already merged → no second merge |
| PR-008 | No PR → clear text, no GitHub mutation |
| PR-009 | Telegram `send_document` error → PR/job unchanged |
| PR-010 | GitHub merge error → job not `DONE` |
| PR-011 | Confirm after HEAD moved → no merge, must `/merge` again |
| PR-012 | Process restart reloads jobs from `JOBS_STORE_PATH` and notifies the operator |
| PR-013 | Merge callback without job_id still answers Telegram (button does not hang) |

Automated coverage: `tests/test_pr_review_control.py`, `tests/test_bug_regressions.py`, `tests/test_review_followup.py`.

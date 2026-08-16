# Detailed Technical Specification

AI Software Pipeline — Telegram control channel over GitHub Copilot coding agent.

## Scope

Telegram `/new` creates a GitHub Issue, assigns `copilot-swe-agent[bot]`, waits for a Pull Request and GitHub Actions, then lets the operator review and merge from Telegram.

## Actors

- Operator (authorized Telegram user)
- Pipeline orchestrator
- GitHub Copilot coding agent (`copilot-swe-agent[bot]`)
- GitHub Actions in the **target** repository

## Functional requirements

### FR-1 Task intake

`/new <text>` creates an Issue in `GITHUB_OWNER/GITHUB_REPO` and assigns the coding agent. If GitHub accepts the request but does not actually assign the agent, the job becomes `ADAPTER_ERROR`.

### FR-2 Progress without a webhook

Webhook is not the only event source. After `CODING_AGENT_RUNNING` the orchestrator starts `watch_issue()` and a stale watchdog. Polling events go through the same `process_event()` / `processed_event_ids` path as webhooks.

If a job stays in `CODING_AGENT_RUNNING` or `WAIT_TESTS` longer than `CODING_AGENT_STALE_TIMEOUT_SEC` without events, the operator gets a warning. The job is **not** moved to a terminal state.

### FR-3 Agent identity

One official login is used for assignment, comments, and PRs: `copilot-swe-agent[bot]` (alias `copilot-swe-agent`). The reviewer bot `copilot-pull-request-reviewer[bot]` is ignored.

### FR-4.2 Fix trigger

On CI failure the pipeline publishes exactly:

    @copilot Fix the failing tests

    ```
    <error log>
    ```

The only production path is `coding_agent.trigger_fix_iteration`.

### FR-5 Agent completion

Primary signal: non-empty `requested_reviewers`, or the PR left draft after we already saw it as draft. A PR opened as non-draft without reviewers is not treated as complete. Issue closed and completion-text from the coding-agent login are fallbacks.

### FR-6 `/diff`

`/diff` returns the current unified diff of the job's PR as a Telegram document `PR-{n}.diff` with caption `PR #{n} — актуальный diff для ревью`. Extra arguments (`/diff 123`) are rejected with an explicit message; the command does not run against another PR.

| Condition | Message |
| --- | --- |
| no PR | Для текущей задачи Pull Request ещё не создан. |
| PR closed | Pull Request закрыт. Актуальный diff недоступен. |
| PR merged | Pull Request уже объединён. |
| GitHub error | Не удалось получить diff Pull Request. Попробуйте повторить команду позже. |
| empty diff | В Pull Request нет изменений для передачи на ревью. |
| over Telegram limit | Diff сформирован, но его размер превышает лимит Telegram. + `Полный diff: <pr>.diff` + PR link. The command is complete: the full unified diff stays available on GitHub for an external reviewer. |
| Telegram send error | Не удалось отправить diff в Telegram. + PR link |

The diff is always fetched live (`Accept: application/vnd.github.diff`). No cache, no local agent diff, no PR body, no file list. A Telegram send failure does not change PR/job state. The earlier “PR created” notification is not replaced.

### FR-7 `/merge`

`/merge` never merges immediately. It shows status and asks for confirmation. `/merge 123` is rejected: the bot explains that a PR number is not accepted and does not merge anything. Only a bare `/merge` for the current job proceeds.

Merge rights are the Telegram allowlist, not task ownership (`job.user_id`). Any id in `TELEGRAM_ALLOWED_USER_IDS` may confirm or cancel. `confirm_merge` checks the allowlist at entry and again before `merge_pull_request` as defense-in-depth; that is not an atomic authorization guarantee. An allowlist miss raises `Нет доступа.` and does not mutate the job or call GitHub. `/status` uses the same allowlist.

```
PR #{n}

Status: OPEN
CI: PASS
PR: <link>

Объединить Pull Request?
[ Merge ]  [ Cancel ]
```

Checks run on `/merge` and again on confirm (TOCTOU):

- PR belongs to the current job
- PR is open and not merged
- required GitHub Actions completed successfully
- Copilot is not waiting for a user reply
- operator is on the Telegram allowlist
- GitHub allows merge (`mergeable` / `mergeable_state`)
- confirm merges the SHA frozen at `/merge`, not current HEAD; if the SHA changed, merge is denied and the operator must `/merge` again

| Condition | Message |
| --- | --- |
| CI running | Merge пока невозможен: проверки CI ещё выполняются. |
| CI failure | Merge невозможен: CI завершился с ошибкой. |
| already merged | PR #{n} уже объединён. |
| closed without merge | PR закрыт и не может быть объединён. |
| Copilot waiting | Merge пока невозможен: Copilot ожидает ответа пользователя. |
| HEAD moved | PR изменился с момента /merge. Повторите /merge. |
| GitHub merge error | Не удалось выполнить merge PR #{n}. Причина: \<GitHub\> |

Success: `PR #{n} успешно объединён.` + `Задача завершена.` + PR URL, job → `DONE`. GitHub merge errors leave the job non-DONE. Telegram never calls GitHub; merge goes Orchestrator → GitHubPort → GitHub Adapter → API.

### FR-8 Authorization

`/diff` and `/merge` are limited to `TELEGRAM_ALLOWED_USER_IDS`. Telegram auth does not replace GitHub token permissions. Commands never accept a raw PR number (`/merge 123` is out of scope).

## Non-functional

- GitHub is the source of truth for PR state and the merge itself.
- Telegram adapter does not call GitHub API.
- Chain: Telegram → Adapter → Orchestrator → GitHubPort → GitHub Adapter → API.
- No separate Telegram FSM.
- Jobs and processed event IDs are stored in `JOBS_STORE_PATH` so a process restart can recover in-flight work. Empty path keeps an in-memory store (tests).

## Out of scope

Auto-merge, merge by PR number, automated AI review, branch deletion, a merge workflow.

## ISSUE-001

The **target** repository must contain `.github/workflows/` before the agent is expected to produce a `workflow_run`, or the issue text must ask the agent to create minimal CI. This is a process requirement, not an orchestrator bug.

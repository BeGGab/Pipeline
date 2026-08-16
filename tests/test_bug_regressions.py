"""Regressions for BUG-001 … BUG-009."""

from __future__ import annotations

from datetime import timedelta

import pytest

from adapters.coding_agent.adapter import CodingAgentAdapter, _FIX_TRIGGER_TEXT
from adapters.github.actions import ActionsClient
from adapters.github.issues import (
    _COPILOT_ASSIGNEE,
    _COPILOT_ASSIGNEE_ALIASES,
    IssuesClient,
)
from adapters.github.models import GitHubPullRequest, GitHubUser
from config.settings import Settings
from domain.clock import utcnow
from domain.errors import AssignmentError
from domain.models import EventType, JobState, PipelineEvent
from tests.conftest import FakeCodingAgent, open_pr, seed_job


class _Comment:
    def __init__(self, login: str, body: str, id: int = 1) -> None:
        self.id = id
        self.body = body
        self.user = type("U", (), {"login": login})()


class _PRClient:
    def __init__(self, pr: GitHubPullRequest) -> None:
        self.pr = pr

    async def get_pull_request(self, number: int) -> GitHubPullRequest:
        return self.pr


class _IssueClient:
    def __init__(self, state: str = "open") -> None:
        self.state = state

    async def get_issue(self, number: int) -> dict:
        return {"state": self.state}


class _Comments:
    def __init__(self, comments) -> None:
        self.comments = comments

    async def list_issue_comments(self, number: int):
        return self.comments


class _Github:
    def __init__(self, pr=None, comments=None, issue_state="open") -> None:
        self.pull_requests = _PRClient(pr) if pr else None
        self.comments = _Comments(comments or [])
        self.issues = _IssueClient(issue_state)


async def test_bug001_watch_issue_drives_process_event_without_webhook(harness):
    jobs, runner = harness["jobs"], harness["runner"]
    job = await seed_job(jobs, state=JobState.CODING_AGENT_RUNNING, pr_number=None)

    async def events(issue_number: int):
        yield PipelineEvent(
            event_id="e1",
            type=EventType.PR_OPENED,
            issue_number=issue_number,
            pr_number=12,
            payload={"html_url": "https://github.com/acme/repo/pull/12"},
        )
        yield PipelineEvent(
            event_id="e2",
            type=EventType.TESTS_PASSED,
            issue_number=issue_number,
            pr_number=12,
        )

    harness["coding_agent"].watch_issue = events
    await runner._run_watch_issue(job)
    fresh = await jobs.get(job.id)
    assert fresh.pr_number == 12
    assert fresh.state == JobState.TEST_PASSED
    assert "e1" in runner.processed_event_ids
    assert "e2" in runner.processed_event_ids


async def test_bug001_stale_watchdog_warns_but_does_not_fail(harness, monkeypatch):
    jobs, runner, notifier = harness["jobs"], harness["runner"], harness["notifier"]
    job = await seed_job(jobs, state=JobState.CODING_AGENT_RUNNING)
    job.last_event_at = utcnow() - timedelta(seconds=2000)
    await jobs.save(job)

    sleeps = {"n": 0}

    async def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] >= 2:
            raise asyncio_cancel()

    class asyncio_cancel(Exception):
        pass

    import orchestrator.pipeline_runner as mod

    monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio_cancel):
        await runner._run_stale_watchdog(job)

    fresh = await jobs.get(job.id)
    assert fresh.state == JobState.CODING_AGENT_RUNNING
    assert any("Нет новостей от GitHub" in text for _, text in notifier.texts)


async def test_bug002_003_fix_trigger_text_and_single_path(harness):
    jobs, runner, agent = harness["jobs"], harness["runner"], harness["coding_agent"]
    job = await seed_job(jobs)
    await runner._handle_test_failure(job, "E: boom")
    assert agent.fix_calls == [(3, "E: boom")]
    assert _FIX_TRIGGER_TEXT == "@copilot Fix the failing tests"
    assert not hasattr(harness["github"], "trigger_fix")


def test_bug004_single_copilot_login():
    settings = Settings()
    assert settings.copilot_username == "copilot-swe-agent[bot]"
    assert _COPILOT_ASSIGNEE == "copilot-swe-agent[bot]"
    assert "github-copilot[bot]" not in _COPILOT_ASSIGNEE_ALIASES


class _HttpAssign:
    def __init__(self, assignees) -> None:
        self.assignees = assignees

    async def post(self, path, json=None):
        class Resp:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        return Resp({"assignees": self.assignees})


async def test_bug005_assign_without_assignee_raises():
    client = IssuesClient(_HttpAssign([]), "acme", "repo", graphql=None)
    with pytest.raises(AssignmentError, match="не назначил"):
        await client.assign_copilot(3)


async def test_bug006_completion_uses_draft_and_reviewers():
    settings = Settings()
    pr = GitHubPullRequest(
        number=12,
        html_url="https://example/pr/12",
        state="open",
        draft=False,
        requested_reviewers=[GitHubUser(login="owner")],
    )
    adapter = CodingAgentAdapter(_Github(pr=pr, comments=[]), settings)
    assert await adapter.detect_task_completion(3, 12) is True


async def test_bug007_reviewer_bot_is_ignored():
    settings = Settings()
    adapter = CodingAgentAdapter(_Github(), settings)
    assert adapter._is_coding_agent_login("copilot-swe-agent[bot]") is True
    assert adapter._is_coding_agent_login("copilot-pull-request-reviewer[bot]") is False
    event = adapter.parse_webhook_event(
        "issue_comment",
        {
            "action": "created",
            "issue": {"number": 3},
            "comment": {
                "id": 99,
                "body": "Looks good?",
                "user": {"login": "copilot-pull-request-reviewer[bot]"},
            },
        },
    )
    assert event is None


class _HttpRuns:
    def __init__(self, runs) -> None:
        self.runs = runs

    async def get(self, path, params=None):
        class Resp:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        return Resp({"workflow_runs": self.runs})


async def test_bug008_latest_completed_run_skips_in_progress():
    client = ActionsClient(
        _HttpRuns(
            [
                {"id": 2, "status": "in_progress", "conclusion": None},
                {"id": 1, "status": "completed", "conclusion": "failure"},
            ]
        ),
        "acme",
        "repo",
    )
    run = await client.get_latest_run_for_branch("main")
    assert run["id"] == 1
    assert run["conclusion"] == "failure"


async def test_bug009_review_comment_is_honest(harness):
    jobs, runner, github = harness["jobs"], harness["runner"], harness["github"]
    job = await seed_job(jobs, state=JobState.TEST_PASSED)
    await runner._process_state(job)
    assert github.review_comments == [
        "Pipeline check: CI passed, no automated review configured."
    ]

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.coding_agent.adapter import CodingAgentAdapter, _FIX_TRIGGER_TEXT
from config.settings import Settings
from domain.models import EventType, JobState, PipelineEvent
from tests.conftest import open_pr, seed_job
from webhooks.router import build_webhook_router, verify_signature


async def test_recover_reuses_existing_issue(harness):
    jobs, runner, github = harness["jobs"], harness["runner"], harness["github"]
    await seed_job(
        jobs,
        state=JobState.TASK_ACCEPTED,
        issue_number=3,
        issue_url="https://github.com/acme/repo/issues/3",
        pr_number=None,
    )
    await runner.recover_active_jobs()
    assert github.created_issues == []
    assert harness["coding_agent"].trigger_calls == [3]


async def test_new_job_stops_previous(harness):
    jobs, runner = harness["jobs"], harness["runner"]
    old = await seed_job(jobs, state=JobState.CODING_AGENT_RUNNING, pr_number=None)
    await runner.start_job(chat_id=100, user_id=7, title="next", body="next task")
    fresh = await jobs.get(old.id)
    assert fresh.state == JobState.FAILED
    assert any("остановлена" in text for _, text in harness["notifier"].texts)


async def test_confirm_merge_requires_pending(harness):
    jobs, store, runner = harness["jobs"], harness["store"], harness["runner"]
    job = await seed_job(jobs, state=JobState.WAIT_TESTS)
    store.prs[12] = open_pr()
    store.runs["copilot/fix-12"] = [
        {"id": 1, "status": "completed", "conclusion": "success"}
    ]
    await runner.confirm_merge(job.id, True)
    assert store.merge_calls == []
    assert any("/merge" in text for _, text in harness["notifier"].texts)


async def test_webhook_and_poll_share_event_ids():
    adapter = CodingAgentAdapter(github=None, settings=Settings())
    poll = adapter._event_from_comment(
        3,
        {
            "id": 99,
            "body": "Working on it",
            "user": {"login": "copilot-swe-agent[bot]"},
        },
    )
    hook = adapter.parse_webhook_event(
        "issue_comment",
        {
            "action": "created",
            "issue": {"number": 3},
            "comment": {
                "id": 99,
                "body": "Working on it",
                "user": {"login": "copilot-swe-agent[bot]"},
            },
        },
    )
    assert poll is not None and hook is not None
    assert poll.event_id == hook.event_id == "comment-started-99"


async def test_cancelled_run_does_not_trigger_fix():
    adapter = CodingAgentAdapter(github=None, settings=Settings())
    event = adapter.parse_webhook_event(
        "workflow_run",
        {
            "workflow_run": {
                "id": 5,
                "status": "completed",
                "conclusion": "cancelled",
                "head_branch": "copilot/issue-3",
                "pull_requests": [{"number": 12}],
            }
        },
    )
    assert event is None


async def test_bare_question_mark_is_not_copilot_question():
    adapter = CodingAgentAdapter(github=None, settings=Settings())
    event = adapter._event_from_comment(
        3,
        {
            "id": 1,
            "body": "Pushed a commit. Next step?",
            "user": {"login": "copilot-swe-agent[bot]"},
        },
    )
    assert event is not None
    assert event.type == EventType.AGENT_STARTED


async def test_terminal_job_ignores_events(harness):
    jobs, runner, notifier = harness["jobs"], harness["runner"], harness["notifier"]
    await seed_job(jobs, state=JobState.DONE)
    before = len(notifier.texts)
    await runner.process_event(
        PipelineEvent(
            event_id="late",
            type=EventType.AGENT_STARTED,
            issue_number=3,
        )
    )
    assert len(notifier.texts) == before


async def test_fix_log_is_truncated(harness):
    agent = harness["coding_agent"]
    from adapters.coding_agent.adapter import CodingAgentAdapter

    class _Comments:
        def __init__(self):
            self.bodies = []

        async def create_issue_comment(self, issue_number, body):
            self.bodies.append(body)

    class _Github:
        comments = _Comments()

    real = CodingAgentAdapter(_Github(), Settings())
    await real.trigger_fix_iteration(3, "E" * 20_000)
    posted = real.github.comments.bodies[0]
    assert posted.startswith(_FIX_TRIGGER_TEXT)
    assert "...[truncated]" in posted
    assert len(posted) < 20_000


def test_webhook_rejects_missing_secret():
    class _Settings:
        github_webhook_secret = ""

    class _Container:
        settings = _Settings()
        coding_agent = None
        runner = None

    app = FastAPI()
    app.include_router(build_webhook_router(_Container()))
    response = TestClient(app).post("/webhooks/github", json={"action": "ping"})
    assert response.status_code == 503


def test_signature_still_checks_when_secret_set():
    body = b'{"ok":true}'
    assert verify_signature("s3cret", body, "sha256=nope") is False


async def test_observed_merge_marks_job_done(harness):
    jobs, store, runner = harness["jobs"], harness["store"], harness["runner"]
    job = await seed_job(jobs, state=JobState.WAIT_TESTS)
    store.prs[12] = open_pr(merged=True, state="closed")
    await runner.request_merge(job.id)
    fresh = await jobs.get(job.id)
    assert fresh.state == JobState.DONE
    assert store.merge_calls == []


async def test_recover_watches_test_passed(harness):
    jobs, runner = harness["jobs"], harness["runner"]
    job = await seed_job(jobs, state=JobState.TEST_PASSED)
    await runner.recover_active_jobs()
    assert job.id in runner._watch_tasks


async def test_issue_closed_ids_match():
    adapter = CodingAgentAdapter(github=None, settings=Settings())
    hook = adapter.parse_webhook_event(
        "issues",
        {"action": "closed", "issue": {"number": 3}},
    )
    assert hook is not None
    assert hook.event_id == "issue-closed-3"

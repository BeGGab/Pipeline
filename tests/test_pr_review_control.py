"""PR-001 … PR-010 — /diff and /merge control channel."""

from __future__ import annotations

from domain.models import JobState
from tests.conftest import open_pr, seed_job


async def test_pr001_diff_sends_file_and_does_not_mutate_pr(harness):
    jobs, store, runner, notifier = (
        harness["jobs"],
        harness["store"],
        harness["runner"],
        harness["notifier"],
    )
    job = await seed_job(jobs)
    store.prs[12] = open_pr()
    store.diffs[12] = "diff --git a/x b/x\n+hello\n"

    await runner.request_diff(job.id)

    assert store.diff_calls == [12]
    assert store.merge_calls == []
    assert store.prs[12].merged is False
    assert store.prs[12].state == "open"
    assert len(notifier.documents) == 1
    doc = notifier.documents[0]
    assert doc["filename"] == "PR-12.diff"
    assert doc["content"] == b"diff --git a/x b/x\n+hello\n"
    assert "актуальный diff" in doc["caption"]
    fresh = await jobs.get(job.id)
    assert fresh.state == JobState.WAIT_TESTS


async def test_pr002_second_diff_fetches_new_commit(harness):
    jobs, store, runner = harness["jobs"], harness["store"], harness["runner"]
    job = await seed_job(jobs)
    store.prs[12] = open_pr()
    store.diffs[12] = "diff v1\n"
    await runner.request_diff(job.id)
    store.diffs[12] = "diff v2 with new commit\n"
    await runner.request_diff(job.id)

    assert store.diff_calls == [12, 12]
    assert harness["notifier"].documents[-1]["content"] == b"diff v2 with new commit\n"


async def test_pr003_merge_asks_confirmation_and_does_not_merge(harness):
    jobs, store, runner, notifier = (
        harness["jobs"],
        harness["store"],
        harness["runner"],
        harness["notifier"],
    )
    job = await seed_job(jobs)
    store.prs[12] = open_pr()
    store.runs["copilot/fix-12"] = [
        {"id": 1, "status": "completed", "conclusion": "success"}
    ]

    await runner.request_merge(job.id)

    assert store.merge_calls == []
    assert len(notifier.confirmations) == 1
    assert "CI: PASS" in notifier.confirmations[0]["text"]
    fresh = await jobs.get(job.id)
    assert fresh.state == JobState.MERGE_CONFIRMATION_PENDING
    assert fresh.merge_head_sha == "abc123"


async def test_pr004_confirm_merge_sets_done(harness):
    jobs, store, runner, notifier = (
        harness["jobs"],
        harness["store"],
        harness["runner"],
        harness["notifier"],
    )
    job = await seed_job(
        jobs,
        state=JobState.MERGE_CONFIRMATION_PENDING,
        merge_head_sha="abc123",
        state_before_merge=JobState.WAIT_TESTS,
    )
    store.prs[12] = open_pr()
    store.runs["copilot/fix-12"] = [
        {"id": 1, "status": "completed", "conclusion": "success"}
    ]

    await runner.confirm_merge(job.id, True)

    assert store.merge_calls == [{"repository": "acme/repo", "number": 12, "sha": "abc123"}]
    fresh = await jobs.get(job.id)
    assert fresh.state == JobState.DONE
    assert any("успешно объединён" in text for _, text in notifier.texts)


async def test_pr005_ci_failure_blocks_merge(harness):
    jobs, store, runner = harness["jobs"], harness["store"], harness["runner"]
    job = await seed_job(jobs)
    store.prs[12] = open_pr()
    store.runs["copilot/fix-12"] = [
        {"id": 1, "status": "completed", "conclusion": "failure"}
    ]

    await runner.request_merge(job.id)

    assert store.merge_calls == []
    assert any("CI завершился с ошибкой" in text for _, text in harness["notifier"].texts)
    fresh = await jobs.get(job.id)
    assert fresh.state != JobState.DONE


async def test_pr006_ci_running_blocks_merge(harness):
    jobs, store, runner = harness["jobs"], harness["store"], harness["runner"]
    job = await seed_job(jobs)
    store.prs[12] = open_pr()
    store.runs["copilot/fix-12"] = [
        {"id": 1, "status": "in_progress", "conclusion": None}
    ]

    await runner.request_merge(job.id)

    assert store.merge_calls == []
    assert any("ещё выполняются" in text for _, text in harness["notifier"].texts)


async def test_pr007_already_merged_is_idempotent(harness):
    jobs, store, runner = harness["jobs"], harness["store"], harness["runner"]
    job = await seed_job(jobs)
    store.prs[12] = open_pr(merged=True, state="closed")

    await runner.request_merge(job.id)

    assert store.merge_calls == []
    assert any("уже объединён" in text for _, text in harness["notifier"].texts)


async def test_pr008_no_pr_no_github_mutation(harness):
    jobs, store, runner, notifier = (
        harness["jobs"],
        harness["store"],
        harness["runner"],
        harness["notifier"],
    )
    job = await seed_job(jobs, pr_number=None, pr_url="")

    await runner.request_diff(job.id)
    await runner.request_merge(job.id)

    assert store.diff_calls == []
    assert store.merge_calls == []
    assert any("ещё не создан" in text for _, text in notifier.texts)


async def test_pr009_telegram_document_failure_does_not_change_job(harness):
    jobs, store, runner, notifier = (
        harness["jobs"],
        harness["store"],
        harness["runner"],
        harness["notifier"],
    )
    job = await seed_job(jobs)
    store.prs[12] = open_pr()
    store.diffs[12] = "diff --git a/x b/x\n"
    notifier.fail_document = True

    await runner.request_diff(job.id)

    fresh = await jobs.get(job.id)
    assert fresh.state == JobState.WAIT_TESTS
    assert store.prs[12].merged is False
    assert any("Не удалось отправить diff" in text for _, text in notifier.texts)


async def test_pr010_github_merge_failure_does_not_mark_done(harness):
    jobs, store, runner = harness["jobs"], harness["store"], harness["runner"]
    job = await seed_job(
        jobs,
        state=JobState.MERGE_CONFIRMATION_PENDING,
        merge_head_sha="abc123",
        state_before_merge=JobState.WAIT_TESTS,
    )
    store.prs[12] = open_pr()
    store.runs["copilot/fix-12"] = [
        {"id": 1, "status": "completed", "conclusion": "success"}
    ]
    store.fail_merge = "required status check is pending"

    await runner.confirm_merge(job.id, True)

    fresh = await jobs.get(job.id)
    assert fresh.state != JobState.DONE
    assert any("Не удалось выполнить merge" in text for _, text in harness["notifier"].texts)
    assert any("required status check" in text for _, text in harness["notifier"].texts)

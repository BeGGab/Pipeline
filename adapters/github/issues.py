from __future__ import annotations

from domain.errors import AssignmentError

# Агент использует один логин copilot-swe-agent[bot]
# и для назначения, и для комментариев/PR.
# Предположение про отдельный github-copilot[bot] — ошибочное, не используем.
_COPILOT_ASSIGNEE = "copilot-swe-agent[bot]"
_COPILOT_ASSIGNEE_ALIASES = frozenset({
    "copilot-swe-agent[bot]",
    "copilot-swe-agent",
})


class IssuesClient:
    def __init__(self, http, owner: str, repo: str, graphql=None) -> None:
        self._http = http
        self._owner = owner
        self._repo = repo
        self._graphql = graphql

    async def create_issue(self, title: str, body: str) -> dict:
        resp = await self._http.post(
            f"/repos/{self._owner}/{self._repo}/issues",
            json={"title": title, "body": body},
        )
        return resp.json()

    async def get_issue(self, issue_number: int) -> dict:
        resp = await self._http.get(
            f"/repos/{self._owner}/{self._repo}/issues/{issue_number}"
        )
        return resp.json()

    async def assign_copilot(self, issue_number: int):
        resp = await self._http.post(
            f"/repos/{self._owner}/{self._repo}/issues/{issue_number}/assignees",
            json={"assignees": [_COPILOT_ASSIGNEE]},
        )
        body = resp.json()
        assignees = body.get("assignees") or []
        if self._assignees_include_copilot(assignees):
            return body
        graphql_body = await self._assign_via_graphql(issue_number)
        if graphql_body and self._assignees_include_copilot(
            graphql_body.get("assignees") or []
        ):
            return graphql_body
        raise AssignmentError(
            f"GitHub принял запрос, но не назначил {_COPILOT_ASSIGNEE}. "
            "Включите Copilot coding agent и проверьте права токена."
        )

    def _assignees_include_copilot(self, assignees) -> bool:
        allowed = {alias.lower() for alias in _COPILOT_ASSIGNEE_ALIASES}
        for item in assignees:
            login = item.get("login") if isinstance(item, dict) else str(item)
            if (login or "").lower() in allowed:
                return True
        return False

    async def _assign_via_graphql(self, issue_number: int):
        if self._graphql is None:
            return None
        try:
            issue_id, actor_id = await self._graphql.resolve_assignable_and_actor(
                owner=self._owner,
                repo=self._repo,
                issue_number=issue_number,
                actor_login=_COPILOT_ASSIGNEE,
            )
            data = await self._graphql.execute(
                """
                mutation($assignableId: ID!, $actorIds: [ID!]!) {
                  replaceActorsForAssignable(input: {
                    assignableId: $assignableId, actorIds: $actorIds
                  }) {
                    assignable {
                      ... on Issue {
                        assignees(first: 10) { nodes { login } }
                      }
                    }
                  }
                }
                """,
                {"assignableId": issue_id, "actorIds": [actor_id]},
            )
            nodes = (
                data.get("replaceActorsForAssignable", {})
                .get("assignable", {})
                .get("assignees", {})
                .get("nodes")
                or []
            )
            return {"assignees": nodes}
        except Exception:
            return None

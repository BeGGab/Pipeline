from __future__ import annotations

import httpx


class GitHubGraphQL:
    def __init__(self, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "ai-software-pipeline",
            },
            timeout=30.0,
        )

    async def execute(self, query: str, variables: dict | None = None) -> dict:
        resp = await self._client.post(
            "/graphql",
            json={"query": query, "variables": variables or {}},
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(payload["errors"])
        return payload.get("data") or {}

    async def resolve_assignable_and_actor(
        self,
        *,
        owner: str,
        repo: str,
        issue_number: int,
        actor_login: str,
    ) -> tuple[str, str]:
        data = await self.execute(
            """
            query($owner: String!, $repo: String!, $number: Int!, $login: String!) {
              repository(owner: $owner, name: $repo) {
                issue(number: $number) { id }
                assignableUsers(query: $login, first: 10) {
                  nodes { id login }
                }
              }
            }
            """,
            {
                "owner": owner,
                "repo": repo,
                "number": issue_number,
                "login": actor_login,
            },
        )
        issue = (data.get("repository") or {}).get("issue") or {}
        issue_id = issue.get("id")
        actor_id = None
        for node in (
            (data.get("repository") or {}).get("assignableUsers", {}).get("nodes") or []
        ):
            if (node.get("login") or "").lower() == actor_login.lower():
                actor_id = node.get("id")
                break
        if not actor_id:
            suggested = await self.execute(
                """
                query($owner: String!, $repo: String!, $login: String!) {
                  repository(owner: $owner, name: $repo) {
                    suggestedActors(query: $login, first: 10) {
                      nodes {
                        ... on Bot { id login }
                        ... on User { id login }
                      }
                    }
                  }
                }
                """,
                {"owner": owner, "repo": repo, "login": actor_login},
            )
            for node in (
                (suggested.get("repository") or {})
                .get("suggestedActors", {})
                .get("nodes")
                or []
            ):
                if (node.get("login") or "").lower() == actor_login.lower():
                    actor_id = node.get("id")
                    break
        if not issue_id or not actor_id:
            raise RuntimeError(
                f"Cannot resolve GraphQL ids for issue #{issue_number} / {actor_login}"
            )
        return issue_id, actor_id

    async def aclose(self) -> None:
        await self._client.aclose()

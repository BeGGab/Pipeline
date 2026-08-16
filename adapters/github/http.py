from __future__ import annotations

import httpx


class GitHubHttp:
    def __init__(self, token: str, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ai-software-pipeline",
            },
            timeout=timeout,
        )

    async def get(self, path: str, **kwargs) -> httpx.Response:
        resp = await self._client.get(path, **kwargs)
        resp.raise_for_status()
        return resp

    async def post(self, path: str, **kwargs) -> httpx.Response:
        resp = await self._client.post(path, **kwargs)
        resp.raise_for_status()
        return resp

    async def put(self, path: str, **kwargs) -> httpx.Response:
        resp = await self._client.put(path, **kwargs)
        resp.raise_for_status()
        return resp

    async def aclose(self) -> None:
        await self._client.aclose()

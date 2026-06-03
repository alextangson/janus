from __future__ import annotations

import httpx


class HAClient:
    """唯一碰 HA 网络的模块。拉 /api/states + /api/services。"""

    def __init__(self, base_url: str, token: str, client=None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.client = client if client is not None else httpx.Client(timeout=timeout)

    def fetch(self) -> tuple[list, list]:
        headers = {"Authorization": f"Bearer {self.token}"}
        states = self._get("/api/states", headers)
        services = self._get("/api/services", headers)
        return states, services

    def _get(self, path: str, headers: dict):
        resp = self.client.get(self.base_url + path, headers=headers)
        resp.raise_for_status()
        return resp.json()

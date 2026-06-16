from __future__ import annotations

import json
import httpx


def _default_ws_connect(url: str, timeout: float = 10.0):
    import websocket  # websocket-client, lazy import: only needed for real connections

    return websocket.create_connection(url, timeout=timeout)


class HAClient:
    """唯一碰 HA 网络的模块。拉 /api/states + /api/services。"""

    def __init__(self, base_url: str, token: str, client=None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.client = client if client is not None else httpx.Client(timeout=timeout)

    def fetch(self) -> tuple[list, list]:
        headers = {"Authorization": f"Bearer {self.token}"}
        states = self._get("/api/states", headers)
        services = self._get("/api/services", headers)
        return states, services

    def fetch_config(self) -> dict:
        """拉 /api/config(单位制等实例配置)。"""
        return self._get("/api/config", {"Authorization": f"Bearer {self.token}"})

    def _get(self, path: str, headers: dict):
        resp = self.client.get(self.base_url + path, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def call_service(self, domain: str, service: str, entity_id: str, params: dict | None = None):
        headers = {"Authorization": f"Bearer {self.token}"}
        data = {"entity_id": entity_id, **(params or {})}
        resp = self.client.post(f"{self.base_url}/api/services/{domain}/{service}", headers=headers, json=data)
        resp.raise_for_status()
        return resp.json()

    def fetch_registries(self, ws_connect=None) -> tuple[list, list, list]:
        """一次性 WS 拉三张注册表:(entities, devices, areas)。"""
        ws_connect = ws_connect or (lambda url: _default_ws_connect(url, self.timeout))
        conn = ws_connect(self._ws_url())
        try:
            self._ws_auth(conn)
            entities = self._ws_command(conn, 1, "config/entity_registry/list")
            devices = self._ws_command(conn, 2, "config/device_registry/list")
            areas = self._ws_command(conn, 3, "config/area_registry/list")
            return entities, devices, areas
        finally:
            conn.close()

    def _ws_url(self) -> str:
        scheme = "wss" if self.base_url.startswith("https") else "ws"
        host = self.base_url.split("://", 1)[1]
        return f"{scheme}://{host}/api/websocket"

    def _ws_auth(self, conn) -> None:
        first = json.loads(conn.recv())
        if first.get("type") != "auth_required":
            raise RuntimeError(f"意外的 WS 首条消息: {first.get('type')}")
        conn.send(json.dumps({"type": "auth", "access_token": self.token}))
        reply = json.loads(conn.recv())
        if reply.get("type") != "auth_ok":
            raise RuntimeError(f"WS 鉴权失败: {reply.get('type')} {reply.get('message', '')}")

    def _ws_command(self, conn, msg_id: int, cmd_type: str) -> list:
        conn.send(json.dumps({"id": msg_id, "type": cmd_type}))
        while True:
            msg = json.loads(conn.recv())
            if msg.get("id") != msg_id:
                continue  # 跳过无关事件
            if not msg.get("success", False):
                raise RuntimeError(f"WS 命令 {cmd_type} 失败: {msg.get('error')}")
            return msg.get("result") or []

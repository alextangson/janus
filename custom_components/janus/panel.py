"""HA 审计面板的 WS 数据接口。含 homeassistant 导入,只能被 __init__.py 函数内导入(红线)。"""
from __future__ import annotations

import logging

from homeassistant.components import websocket_api
from homeassistant.core import callback

from .const import DOMAIN
from .gatekeeper.audit import display_status

_LOGGER = logging.getLogger(__name__)


def _get_audit(hass):
    """取第一个带 audit 的 entry data(单 entry 是常态)。"""
    for data in hass.data.get(DOMAIN, {}).values():
        if isinstance(data, dict) and data.get("audit") is not None:
            return data["audit"]
    return None


@websocket_api.websocket_command({"type": "janus/audit/list"})
@callback
def ws_list_decisions(hass, connection, msg):
    audit = _get_audit(hass)
    rows = audit.snapshot() if audit else []
    decisions = [{**r, "status": display_status(r)} for r in reversed(rows)]
    connection.send_result(msg["id"], {"decisions": decisions})

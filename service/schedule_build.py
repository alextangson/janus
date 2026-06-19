from __future__ import annotations

import uuid

from gatekeeper.models import ScheduleIntent

from .schedule_store import ScheduleEntry
from .schedule_time import compute_next_fire

_PRESET = {
    "daily": [0, 1, 2, 3, 4, 5, 6],
    "weekday": [0, 1, 2, 3, 4],
    "weekend": [5, 6],
}


def entry_from_intent(
    device_id: str,
    operation: str,
    params: dict,
    intent: ScheduleIntent,
    *,
    tz: str,
    now: float,
) -> ScheduleEntry:
    """把 LLM 给的 ScheduleIntent 描述符 + 已许可动作,确定性地转成 ScheduleEntry。

    LLM 不算 epoch —— 这里用 compute_next_fire 算 next_fire_at。
    intent 已经过 engine 的 _valid_intent 形状校验,此处不再复验范围。
    """
    if intent.kind == "recurring":
        minute_of_day = intent.hour * 60 + intent.minute
        days = _PRESET[intent.recurrence]
        nf = compute_next_fire(
            kind="recurring",
            at=None,
            minute_of_day=minute_of_day,
            days=days,
            tz_name=tz,
            after=now,
        )
        kind, at = "recurring", None

    elif intent.kind == "once" and intent.relative_seconds is not None:
        at = now + intent.relative_seconds
        nf = compute_next_fire(
            kind="once",
            at=at,
            minute_of_day=None,
            days=None,
            tz_name=tz,
            after=now,
        )
        kind, minute_of_day, days = "once", None, None

    elif intent.kind == "once":  # 绝对壁钟 hour/minute
        # 复用 recurring helper 扫全周,取下一次该壁钟时刻,再当作 once 落点。
        nf = compute_next_fire(
            kind="recurring",
            at=None,
            minute_of_day=intent.hour * 60 + intent.minute,
            days=[0, 1, 2, 3, 4, 5, 6],
            tz_name=tz,
            after=now,
        )
        kind, at, minute_of_day, days = "once", nf, None, None

    else:
        raise ValueError("无效的定时描述符")

    if nf is None:
        raise ValueError("无可触发时刻")

    return ScheduleEntry(
        id=uuid.uuid4().hex,
        device_id=device_id,
        operation=operation,
        params=dict(params),
        kind=kind,
        at=at,
        minute_of_day=minute_of_day,
        days=days,
        tz=tz,
        enabled=True,
        next_fire_at=nf,
        created_at=now,
    )

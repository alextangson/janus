from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def compute_next_fire(
    *,
    kind: str,
    at: float | None,
    minute_of_day: int | None,
    days: list[int] | None,
    tz_name: str,
    after: float,
    max_lateness: float = 86400.0,
) -> float | None:
    """计算调度下一次触发的 epoch 秒。纯函数,无 IO,仅依赖 stdlib。

    kind="once":未来则到点触发;错过但在宽限内则立即触发(返回 after);超宽限则过期。
    kind="recurring":从 after 的本地日期起逐日向前找,匹配 weekday 且本地时刻严格晚于 after。
    """
    if kind == "once":
        if at is None:
            return None
        if at > after:
            return at
        if after - max_lateness <= at <= after:
            return after
        return None

    if kind == "recurring":
        if not days:
            return None
        if minute_of_day is None:
            return None

        tz = ZoneInfo(tz_name)
        local_after = datetime.fromtimestamp(after, tz)
        hour, minute = divmod(minute_of_day, 60)

        # 从今天起最多扫 8 天以覆盖跨周;只向前看,不回填错过窗口。
        for offset in range(8):
            day = (local_after + timedelta(days=offset)).date()
            if day.weekday() not in days:
                continue
            # 用本地壁钟构造候选时刻;春跳不存在的本地时间 timestamp() 仍给可用值,不抛。
            candidate = datetime(
                day.year, day.month, day.day, hour, minute, tzinfo=tz
            ).timestamp()
            if candidate > after:
                return candidate
        return None

    return None

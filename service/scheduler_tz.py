from __future__ import annotations

from zoneinfo import ZoneInfo


def resolve_tz(ha_client, default: str = "Asia/Shanghai") -> str:
    """从 HA /api/config 的 time_zone 取时区;任何异常/缺失/非法 → default。

    复用 engine_factory 同款 fetch_config()(读 /api/config,内含 time_zone)。
    用 ZoneInfo 校验返回值是真实时区,挡住 HA 返回的脏字符串。
    """
    try:
        config = ha_client.fetch_config()
        tz = config.get("time_zone") if isinstance(config, dict) else None
        if not tz:
            return default
        ZoneInfo(tz)  # 仅校验,无效抛 → 落到 except
        return tz
    except Exception:
        return default

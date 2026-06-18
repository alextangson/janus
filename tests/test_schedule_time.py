from datetime import datetime
from zoneinfo import ZoneInfo

from service.schedule_time import compute_next_fire

SH = "Asia/Shanghai"  # UTC+8, 无 DST,断言确定
NY = "America/New_York"  # 有 DST,仅用于春跳测试


def _epoch(tz_name: str, y: int, mo: int, d: int, h: int, mi: int) -> float:
    """构造某时区某本地时刻的 epoch 秒,供测试做确定性断言。"""
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz_name)).timestamp()


# ---- recurring ----


def test_recurring_today_future_today_matches():
    # 2026-06-18 是周四(weekday=3)。after=10:00,目标 22:30 仍在今天未来。
    after = _epoch(SH, 2026, 6, 18, 10, 0)
    got = compute_next_fire(
        kind="recurring", at=None, minute_of_day=22 * 60 + 30,
        days=[3], tz_name=SH, after=after,
    )
    assert got == _epoch(SH, 2026, 6, 18, 22, 30)


def test_recurring_today_passed_returns_next_match():
    # 2026-06-18 周四,after=23:00,目标 08:00 今天已过 → 下一个周四 06-25。
    after = _epoch(SH, 2026, 6, 18, 23, 0)
    got = compute_next_fire(
        kind="recurring", at=None, minute_of_day=8 * 60,
        days=[3], tz_name=SH, after=after,
    )
    assert got == _epoch(SH, 2026, 6, 25, 8, 0)


def test_recurring_mwf_after_tuesday_returns_wednesday():
    # 2026-06-16 是周二(weekday=1)。days=Mon/Wed/Fri → 周三 06-17。
    after = _epoch(SH, 2026, 6, 16, 12, 0)
    got = compute_next_fire(
        kind="recurring", at=None, minute_of_day=9 * 60,
        days=[0, 2, 4], tz_name=SH, after=after,
    )
    assert got == _epoch(SH, 2026, 6, 17, 9, 0)


def test_recurring_week_wrap_sunday_to_monday():
    # 2026-06-21 是周日(weekday=6)。days=[Mon] → 跨周到次日周一 06-22。
    after = _epoch(SH, 2026, 6, 21, 15, 0)
    got = compute_next_fire(
        kind="recurring", at=None, minute_of_day=7 * 60,
        days=[0], tz_name=SH, after=after,
    )
    assert got == _epoch(SH, 2026, 6, 22, 7, 0)


def test_recurring_days_empty_returns_none():
    after = _epoch(SH, 2026, 6, 18, 10, 0)
    assert compute_next_fire(
        kind="recurring", at=None, minute_of_day=600,
        days=[], tz_name=SH, after=after,
    ) is None


def test_recurring_days_none_returns_none():
    after = _epoch(SH, 2026, 6, 18, 10, 0)
    assert compute_next_fire(
        kind="recurring", at=None, minute_of_day=600,
        days=None, tz_name=SH, after=after,
    ) is None


# ---- once ----


def test_once_future_returns_at():
    after = _epoch(SH, 2026, 6, 18, 10, 0)
    at = _epoch(SH, 2026, 6, 18, 12, 0)
    got = compute_next_fire(
        kind="once", at=at, minute_of_day=None,
        days=None, tz_name=SH, after=after,
    )
    assert got == at


def test_once_recent_past_within_grace_returns_after():
    # at 在 after 之前 1h,< 24h 宽限 → fire now(返回 after)。
    after = _epoch(SH, 2026, 6, 18, 10, 0)
    at = after - 3600.0
    got = compute_next_fire(
        kind="once", at=at, minute_of_day=None,
        days=None, tz_name=SH, after=after,
    )
    assert got == after


def test_once_expired_past_returns_none():
    # at 在 after 之前 25h,超过 24h 宽限 → 过期 None。
    after = _epoch(SH, 2026, 6, 18, 10, 0)
    at = after - 25 * 3600.0
    got = compute_next_fire(
        kind="once", at=at, minute_of_day=None,
        days=None, tz_name=SH, after=after,
    )
    assert got is None


# ---- DST 春跳 ----


def test_recurring_dst_spring_forward_does_not_raise():
    # America/New_York 2026-03-08 02:00→03:00 春跳,02:30(minute_of_day=150)本地不存在。
    # 要求:不抛异常、返回 float、落在该日合理范围内(不做精确 epoch 断言,因本地时刻不存在)。
    # after = 03-08 01:00 EST,目标当天 02:30(不存在)。weekday(周日)=6。
    after = _epoch(NY, 2026, 3, 8, 1, 0)
    got = compute_next_fire(
        kind="recurring", at=None, minute_of_day=150,
        days=[6], tz_name=NY, after=after,
    )
    assert isinstance(got, float)
    # sane range:应在 after 之后,且不晚于当天结束后一天的范围内。
    assert got > after
    assert got < after + 86400.0


# ---- defensive ----


def test_unknown_kind_returns_none():
    after = _epoch(SH, 2026, 6, 18, 10, 0)
    assert compute_next_fire(
        kind="bogus", at=after + 100, minute_of_day=600,
        days=[3], tz_name=SH, after=after,
    ) is None

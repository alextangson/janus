"""注意力安全节流测试:封顶、静默时段、K 次拒绝自抑制(codex #19)。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from gatekeeper.proposals import (Proposal, ProposalThrottle, RecordingSink,
                                  ThrottleConfig)

TZ = ZoneInfo("Asia/Shanghai")


def _ts(mon, day, h, m):
    return datetime(2026, mon, day, h, m, tzinfo=TZ).timestamp()


def _p(key="departure:climate.ac:off", domain="climate"):
    return Proposal(habit_key=key, domain=domain, title="要关空调吗?",
                    device_id="climate.ac", operation="turn_off")


def test_recording_sink_collects():
    s = RecordingSink()
    s.surface(_p())
    assert len(s.surfaced) == 1 and s.surfaced[0].device_id == "climate.ac"


def test_normal_case_surfaces():
    t = ProposalThrottle(tz=TZ)
    assert t.should_surface(_p(), _ts(6, 1, 9, 0)) is True


def test_quiet_hours_block_overnight():
    t = ProposalThrottle(tz=TZ)
    assert t.should_surface(_p(), _ts(6, 1, 23, 0)) is False   # 23:00 静默
    assert t.should_surface(_p(), _ts(6, 1, 2, 0)) is False    # 02:00 静默(跨午夜)
    assert t.should_surface(_p(), _ts(6, 1, 8, 0)) is True     # 08:00 静默止,放行


def test_max_one_per_habit_per_day():
    t = ProposalThrottle(tz=TZ)
    now = _ts(6, 1, 9, 0)
    assert t.should_surface(_p(), now) is True
    t.record_surfaced(_p(), now)
    assert t.should_surface(_p(), _ts(6, 1, 18, 0)) is False    # 当天同习惯第二次被挡
    assert t.should_surface(_p(), _ts(6, 2, 9, 0)) is True      # 次日恢复


def test_max_per_domain_per_day():
    t = ProposalThrottle(tz=TZ)
    for i in range(3):                                          # 3 个不同的 climate 习惯
        p = _p(key=f"departure:climate.ac{i}:off", domain="climate")
        assert t.should_surface(p, _ts(6, 1, 9, i)) is True
        t.record_surfaced(p, _ts(6, 1, 9, i))
    p4 = _p(key="departure:climate.acX:off", domain="climate")
    assert t.should_surface(p4, _ts(6, 1, 10, 0)) is False      # climate 当天第 4 个被挡
    other = _p(key="departure:light.a:off", domain="light")
    assert t.should_surface(other, _ts(6, 1, 10, 0)) is True    # 别的域不受影响


def test_max_per_day_total():
    t = ProposalThrottle(ThrottleConfig(max_per_domain_per_day=99), tz=TZ)
    for i in range(5):
        p = _p(key=f"departure:light.l{i}:off", domain="light")
        assert t.should_surface(p, _ts(6, 1, 9, i)) is True
        t.record_surfaced(p, _ts(6, 1, 9, i))
    p6 = _p(key="departure:light.l6:off", domain="light")
    assert t.should_surface(p6, _ts(6, 1, 10, 0)) is False      # 全天总数到顶


def test_k_rejections_self_suppress():
    t = ProposalThrottle(tz=TZ)
    key = "departure:climate.ac:off"
    for _ in range(3):                                          # K=3 次连续拒绝
        t.record_response(key, accepted=False)
    assert t.is_suppressed(key) is True
    assert t.should_surface(_p(key=key), _ts(6, 5, 9, 0)) is False  # 之后永不再推


def test_accept_resets_rejection_count():
    t = ProposalThrottle(tz=TZ)
    key = "departure:climate.ac:off"
    t.record_response(key, accepted=False)
    t.record_response(key, accepted=False)
    t.record_response(key, accepted=True)                       # 接受 → 清零
    t.record_response(key, accepted=False)
    assert t.is_suppressed(key) is False                        # 没攒够 3 次连续

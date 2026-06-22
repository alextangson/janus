"""主动提议的纯层:Proposal 模型 + ProposalSink 接口 + 注意力安全节流。
无 IO、无 HA;tz/now 由调用方注入,validator.py 风格、可测。

护城河是确认、不是自治;但**烦人会毁掉信任**。本模块实现 codex 深审 #19 的注意力安全:
按习惯/域/天封顶、静默时段、K 次连续拒绝自抑制。投递实现(HA Companion 推送)与触发
监听在 HA 层(component),经 ProposalSink 接口解耦;openclaw 只能当可选 sink,决策门绝不交它。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo


@dataclass(frozen=True)
class Proposal:
    """一条待投递的主动提议(挖掘器候选 → 可确认的动作)。"""
    habit_key: str                 # 习惯唯一键(如 'departure:climate.ac:off')
    domain: str                    # 动作域(light/climate/...),按域封顶用
    title: str                     # 用户可见文案,如 "要关客厅空调吗?"
    device_id: str
    operation: str
    params: dict[str, object] = field(default_factory=dict)


class ProposalSink:
    """投递适配器接口(HA Companion 推送 / app 收件箱 / openclaw)。鸭子类型即可。"""

    def surface(self, proposal: Proposal) -> None:
        raise NotImplementedError


class RecordingSink(ProposalSink):
    """测试/静默期用:只记录,不真投递。"""

    def __init__(self) -> None:
        self.surfaced: list[Proposal] = []

    def surface(self, proposal: Proposal) -> None:
        self.surfaced.append(proposal)


@dataclass(frozen=True)
class ThrottleConfig:
    max_per_habit_per_day: int = 1      # 同一习惯每天最多推一次
    max_per_domain_per_day: int = 3     # 同一动作域每天封顶
    max_per_day_total: int = 5          # 全天总封顶
    quiet_start_min: int = 22 * 60      # 静默时段起(22:00)
    quiet_end_min: int = 8 * 60         # 静默时段止(08:00),跨午夜
    suppress_after_rejections: int = 3  # K 次连续拒绝 → 自抑制该习惯


class ProposalThrottle:
    """注意力安全节流:决定一条提议此刻是否该露出。有状态(进程内),由调用方喂时间戳/响应。"""

    def __init__(self, config: ThrottleConfig = ThrottleConfig(), *, tz: tzinfo) -> None:
        self._cfg = config
        self._tz = tz
        self._surfaced: list[tuple[str, str, float]] = []  # (habit_key, domain, ts)
        self._rejections: dict[str, int] = {}              # habit_key → 连续拒绝数
        self._suppressed: set[str] = set()

    def _date(self, ts: float) -> date:
        return datetime.fromtimestamp(ts, self._tz).date()

    def _minute(self, ts: float) -> int:
        d = datetime.fromtimestamp(ts, self._tz)
        return d.hour * 60 + d.minute

    def _in_quiet(self, ts: float) -> bool:
        m = self._minute(ts)
        qs, qe = self._cfg.quiet_start_min, self._cfg.quiet_end_min
        if qs <= qe:
            return qs <= m < qe
        return m >= qs or m < qe  # 跨午夜

    def should_surface(self, proposal: Proposal, now: float) -> bool:
        if proposal.habit_key in self._suppressed:
            return False
        if self._in_quiet(now):
            return False
        today = self._date(now)
        today_rows = [r for r in self._surfaced if self._date(r[2]) == today]
        if any(r[0] == proposal.habit_key for r in today_rows):
            return False
        if sum(1 for r in today_rows if r[1] == proposal.domain) >= self._cfg.max_per_domain_per_day:
            return False
        if len(today_rows) >= self._cfg.max_per_day_total:
            return False
        return True

    def record_surfaced(self, proposal: Proposal, now: float) -> None:
        self._surfaced.append((proposal.habit_key, proposal.domain, now))

    def record_response(self, habit_key: str, accepted: bool) -> None:
        """用户响应回流:接受 → 清零拒绝计数;拒绝 → 累加,达 K 次自抑制该习惯。"""
        if accepted:
            self._rejections.pop(habit_key, None)
            return
        n = self._rejections.get(habit_key, 0) + 1
        self._rejections[habit_key] = n
        if n >= self._cfg.suppress_after_rejections:
            self._suppressed.add(habit_key)

    def is_suppressed(self, habit_key: str) -> bool:
        return habit_key in self._suppressed

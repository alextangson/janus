"""习惯观察的纯数据层:一次状态跳变 → 一条 Observation;触发来源分类。
无 IO、无 HA、无时间戳(时间由 HA 层落盘时盖),保持可测。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    entity_id: str
    domain: str
    new_state: str
    source: str   # user / automation / physical


def build_observation(entity_id: str, new_state: str, source: str) -> Observation:
    return Observation(entity_id=entity_id, domain=entity_id.split(".")[0],
                       new_state=new_state, source=source)


def classify_source(user_id, parent_id) -> str:
    """谁触发了这次状态变化。user_id 有=人(UI/语音/app);否则 parent_id 有=自动化;
    都没=physical(物理开关/设备直报——也是人的行为信号;注:Janus 自己的动作目前也落这档,第二步剔除)。"""
    if user_id:
        return "user"
    if parent_id:
        return "automation"
    return "physical"

"""习惯观察的纯数据层:一次状态跳变 → 一条 Observation;触发来源分类。
无 IO、无 HA、无时间戳(时间由 HA 层落盘时盖),保持可测。
"""
from __future__ import annotations

from dataclasses import dataclass

# 观察域:动作(light/cover/lock/climate)+ 触发(person/device_tracker 的在/离家)。
# 触发与动作都进 ObservationLog;挖掘器再区分二者。climate 入自治白名单需后续显式开。
OBSERVED_DOMAINS = frozenset(
    {"light", "cover", "lock", "climate", "person", "device_tracker"})


@dataclass(frozen=True)
class Observation:
    entity_id: str
    domain: str
    new_state: str
    source: str   # user / automation / physical / janus


def build_observation(entity_id: str, new_state: str, source: str) -> Observation:
    return Observation(entity_id=entity_id, domain=entity_id.split(".")[0],
                       new_state=new_state, source=source)


def is_observed_domain(entity_id: str) -> bool:
    return entity_id.split(".")[0] in OBSERVED_DOMAINS


def classify_source(user_id, parent_id) -> str:
    """谁触发了这次状态变化。user_id 有=人(UI/语音/app);否则 parent_id 有=自动化;
    都没=physical(物理开关/设备直报/米家等集成——也是人的行为信号)。"""
    if user_id:
        return "user"
    if parent_id:
        return "automation"
    return "physical"


def resolve_source(user_id, parent_id, ctx_id, janus_ctx_ids) -> str:
    """Janus 自己执行的动作(ctx_id 或 parent_id 在 janus 集合里)→ 'janus',与真物理/米家
    行为区分开,永不被当成用户习惯挖掘(否则自治规则回流日志、Janus 从自己身上学)。
    否则按 user/automation/physical 分类。"""
    if janus_ctx_ids and (ctx_id in janus_ctx_ids or parent_id in janus_ctx_ids):
        return "janus"
    return classify_source(user_id, parent_id)

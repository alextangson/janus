from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictInt


class ParamSpec(BaseModel):
    type: Literal["int", "enum"]
    min: int | None = None
    max: int | None = None
    enum: list[str] | None = None
    unit: str | None = None
    required: bool = False


class OperationSpec(BaseModel):
    params: dict[str, ParamSpec] = Field(default_factory=dict)
    dangerous: bool = False


class Device(BaseModel):
    name: str
    type: str
    area: str
    entity_category: str | None = None
    device_id: str | None = None
    operations: dict[str, OperationSpec] = Field(default_factory=dict)


class ScheduleIntent(BaseModel):
    kind: Literal["once", "recurring"]
    hour: int | None = None             # 0..23 (absolute wall-clock)
    minute: int | None = None           # 0..59 (absolute)
    relative_seconds: int | None = None # > 0 (relative once, e.g. 20分钟后 = 1200)
    recurrence: Literal["daily", "weekday", "weekend"] | None = None


class ParseResult(BaseModel):
    recognized: bool
    device_id: str | None = None
    operation: str | None = None
    params: dict[str, bool | int | str] = Field(default_factory=dict)
    candidates: list[str] = Field(default_factory=list)
    inferred: bool = False
    query: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    schedule: ScheduleIntent | None = None
    notes: str = ""


Verdict = Literal["allow", "confirm", "reject", "answer", "ask"]
Stage = Literal["parse", "ambiguous", "feasibility", "inferred", "confidence", "safety", "passed", "error", "query", "param"]


class Decision(BaseModel):
    verdict: Verdict
    stage: Stage
    dangerous: bool = False
    device_id: str | None = None
    operation: str | None = None
    params: dict[str, bool | int | str] = Field(default_factory=dict)
    candidates: list[str] = Field(default_factory=list)
    missing_param: str | None = None
    confidence: float = 0.0
    schedule: ScheduleIntent | None = None
    reason: str = ""

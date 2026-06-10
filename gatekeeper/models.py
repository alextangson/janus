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


class ParseResult(BaseModel):
    recognized: bool
    device_id: str | None = None
    operation: str | None = None
    params: dict[str, bool | int | str] = Field(default_factory=dict)
    candidates: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    notes: str = ""


Verdict = Literal["allow", "confirm", "reject"]
Stage = Literal["parse", "ambiguous", "feasibility", "confidence", "safety", "passed", "error"]


class Decision(BaseModel):
    verdict: Verdict
    stage: Stage
    device_id: str | None = None
    operation: str | None = None
    params: dict[str, bool | int | str] = Field(default_factory=dict)
    candidates: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""

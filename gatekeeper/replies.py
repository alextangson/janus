"""把用户对反问的回复确定性解释成 值/是否/选号。纯函数,无 IO,不调模型。

语音卫星上 STT 给的多是口语形态(二十六度 / 好的 / 第二个),这里统一接住;
拿不准时返回 None/负优先,绝不误执行。
"""
from __future__ import annotations

import re

from .models import ParamSpec
from .queries import _ENUM_ZH

_ZH_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_ZH_NUMERAL_RE = re.compile(r"[零〇一二两三四五六七八九十百]+")


def _parse_zh_numeral(s: str) -> int | None:
    """纯中文数字串 → 0–100,否则 None。"""
    if not s:
        return None
    if s in ("零", "〇"):
        return 0
    if "百" in s:
        return 100 if s in ("百", "一百") else None
    if "十" in s:
        left, _, right = s.partition("十")
        if left and left not in _ZH_DIGIT:
            return None
        if right and right not in _ZH_DIGIT:
            return None
        tens = _ZH_DIGIT[left] if left else 1
        ones = _ZH_DIGIT[right] if right else 0
        return tens * 10 + ones
    if len(s) == 1 and s in _ZH_DIGIT:
        return _ZH_DIGIT[s]
    return None


def zh_to_int(text: str) -> int | None:
    """从自由文本里抽首个中文数字串并解析,否则 None。'一半/两半' 这类分数词拒(一半≠1)。"""
    text = text or ""
    m = _ZH_NUMERAL_RE.search(text)
    if not m:
        return None
    if m.end() < len(text) and text[m.end()] == "半":
        return None
    return _parse_zh_numeral(m.group())


def extract_int(text: str) -> int | None:
    """阿拉伯优先,没有再中文数字。"""
    m = re.search(r"-?\d+", text or "")
    return int(m.group()) if m else zh_to_int(text or "")


def coerce_param(reply: str, spec: ParamSpec) -> int | str | None:
    """把用户对反问的回答确定性转成参数值;转不出 → None(由调用方重问)。不调模型。"""
    if spec.type == "int":
        return extract_int(reply)
    if spec.type == "enum":
        for v in (spec.enum or []):
            if v in reply or _ENUM_ZH.get(v, "\0") in reply:
                return v
    return None


_NEG = ("不", "别", "取消", "算了", "no", "n", "否")
_POS = ("好", "是", "对", "行", "可以", "嗯", "确认", "ok", "yes", "y")


def affirmation(line: str) -> bool | None:
    """口语是/否三态:负优先 → False;再肯定 → True;都不是 → None。"""
    low = (line or "").strip().lower()
    if not low:
        return None
    if any(n in low for n in _NEG):
        return False
    if any(p in low for p in _POS):
        return True
    return None


def choice_index(line: str, n: int) -> int | None:
    """口语选号 → 1..n,否则 None。'第二个'→2 '选第一盏'→1。"""
    idx = extract_int(line)
    return idx if idx is not None and 1 <= idx <= n else None

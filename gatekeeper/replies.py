"""把用户对反问的回复确定性解释成 值/是否/选号。纯函数,无 IO,不调模型。

语音卫星上 STT 给的多是口语形态(二十六度 / 好的 / 第二个),这里统一接住;
拿不准时返回 None/负优先,绝不误执行。
"""
from __future__ import annotations

import re

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

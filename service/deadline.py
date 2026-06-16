from __future__ import annotations

import time
from typing import Callable


class DeadlineExceeded(RuntimeError):
    """请求死线已过:在真打 HA 之前中止执行,避免"报失败却执行了"。"""


class DeadlineHAClient:
    """包装 HAClient:仅在 call_service 前查死线,过线即抛;其余属性/方法透传。"""

    def __init__(self, inner, deadline: float, now: Callable[[], float] = time.monotonic):
        self._inner = inner
        self._deadline = deadline
        self._now = now

    def call_service(self, domain, service, entity_id, params=None):
        if self._now() > self._deadline:
            raise DeadlineExceeded("request deadline exceeded before executing call_service")
        return self._inner.call_service(domain, service, entity_id, params)

    def __getattr__(self, name):
        return getattr(self._inner, name)

from gatekeeper.models import ParseResult


class FakeParser:
    """返回预设解析结果,不调用任何模型。"""

    def __init__(self, result: ParseResult):
        self._result = result

    def parse(self, instruction: str) -> ParseResult:
        return self._result


class RaisingParser:
    """模拟模型 API 故障。"""

    def parse(self, instruction: str) -> ParseResult:
        raise RuntimeError("api down")

import json

from gatekeeper.local_parser import LocalParser
from gatekeeper.prompts import TOOL_NAME


class _Func:
    def __init__(self, payload):
        self.name = TOOL_NAME
        self.arguments = json.dumps(payload)


class _ToolCall:
    def __init__(self, payload):
        self.function = _Func(payload)


class _Msg:
    def __init__(self, payload):
        self.tool_calls = [_ToolCall(payload)]


class _Choice:
    def __init__(self, payload):
        self.message = _Msg(payload)


class _Resp:
    def __init__(self, payload):
        self.choices = [_Choice(payload)]


class _Completions:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _Resp(self._payload)


class _Chat:
    def __init__(self, payload):
        self.completions = _Completions(payload)


class StubOpenAI:
    def __init__(self, payload):
        self.chat = _Chat(payload)


class _NoToolMsg:
    tool_calls = None


class _NoToolChoice:
    message = _NoToolMsg()


class _NoToolResp:
    choices = [_NoToolChoice()]


class StubOpenAINoTool:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                return _NoToolResp()


def test_local_parser_extracts_parseresult(registry):
    payload = {"recognized": True, "device_id": "light.living_room",
               "operation": "turn_on", "params": {}, "confidence": 0.6}
    parser = LocalParser(registry, model="test", client=StubOpenAI(payload))
    pr = parser.parse("开客厅灯")
    assert pr.device_id == "light.living_room"
    assert pr.confidence == 0.6
    # forced tool choice is passed through
    assert parser.client.chat.completions.last_kwargs["tool_choice"]["function"]["name"] == "emit_parse"
    assert parser.client.chat.completions.last_kwargs["temperature"] == 0  # 安全关卡:确定性解码


def test_local_parser_raises_when_no_tool_call(registry):
    import pytest

    parser = LocalParser(registry, model="test", client=StubOpenAINoTool())
    with pytest.raises(ValueError):
        parser.parse("开客厅灯")


def test_default_client_has_bounded_timeout(monkeypatch):
    # 无注入 client 时,默认 OpenAI 客户端必须带有限超时:卡死的本地模型
    # 应让引擎 fail-closed(优雅拒绝),而不是无限挂起。
    from gatekeeper.registry import Registry

    parser = LocalParser(Registry({}), "gemma4")
    assert parser.client.timeout is not None
    assert float(parser.client.timeout) <= 180

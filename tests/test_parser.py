from gatekeeper.parser import ClaudeParser
from gatekeeper.prompts import anthropic_tool, build_user_prompt, TOOL_NAME


class _Block:
    def __init__(self, payload):
        self.type = "tool_use"
        self.name = TOOL_NAME
        self.input = payload


class _Resp:
    def __init__(self, payload):
        self.content = [_Block(payload)]


class _Messages:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _Resp(self._payload)


class StubClient:
    def __init__(self, payload):
        self.messages = _Messages(payload)


class _FlakyMessages:
    def __init__(self, payload, fails):
        self._payload = payload
        self._fails = fails
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self._fails:
            raise RuntimeError("transient")
        return _Resp(self._payload)


class FlakyClient:
    def __init__(self, payload, fails):
        self.messages = _FlakyMessages(payload, fails)


def test_tool_schema_is_built_from_pydantic():
    tool = anthropic_tool()
    assert tool["name"] == "emit_parse"
    assert tool["input_schema"]["type"] == "object"
    assert "confidence" in tool["input_schema"]["properties"]


def test_user_prompt_includes_catalog_and_instruction(registry):
    prompt = build_user_prompt(registry, "开客厅灯")
    assert "light.living_room" in prompt
    assert "开客厅灯" in prompt


def test_parser_extracts_parseresult_from_tool_use(registry):
    payload = {
        "recognized": True, "device_id": "climate.living_room",
        "operation": "set_temperature", "params": {"temperature": 50}, "confidence": 0.93,
    }
    parser = ClaudeParser(registry, model="test", client=StubClient(payload))
    pr = parser.parse("空调开到50度")
    assert pr.device_id == "climate.living_room"
    assert pr.params["temperature"] == 50
    # 强制工具调用的参数确实传给了 client
    assert parser.client.messages.last_kwargs["tool_choice"]["name"] == "emit_parse"


def test_parser_raises_when_no_tool_use(registry):
    class _Empty:
        content = []

    class _C:
        class messages:
            @staticmethod
            def create(**kwargs):
                return _Empty()

    import pytest

    with pytest.raises(ValueError):
        ClaudeParser(registry, model="test", client=_C()).parse("hi")


def test_parser_retries_transient_errors(registry):
    payload = {"recognized": True, "device_id": "light.living_room",
               "operation": "turn_on", "params": {}, "confidence": 0.9}
    client = FlakyClient(payload, fails=2)
    parser = ClaudeParser(registry, model="test", client=client, max_retries=2)
    pr = parser.parse("开客厅灯")
    assert pr.device_id == "light.living_room"
    assert client.messages.calls == 3  # 2 次失败 + 1 次成功


def test_parser_gives_up_after_max_retries(registry):
    import pytest

    payload = {"recognized": True, "device_id": "light.living_room",
               "operation": "turn_on", "params": {}, "confidence": 0.9}
    client = FlakyClient(payload, fails=5)
    parser = ClaudeParser(registry, model="test", client=client, max_retries=2)
    with pytest.raises(RuntimeError):
        parser.parse("开客厅灯")
    assert client.messages.calls == 3  # max_retries + 1 次尝试

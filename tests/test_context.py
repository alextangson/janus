from gatekeeper.context import build_context
from gatekeeper.models import Device, OperationSpec
from gatekeeper.registry import Registry


def _registry():
    return Registry({
        "climate.ac": Device(name="空调", type="climate", area="卧室",
                             operations={"turn_on": OperationSpec()}),
        "light.a": Device(name="主灯", type="light", area="卧室",
                          operations={"turn_on": OperationSpec()}),
    })


def _states():
    return [
        {"entity_id": "light.a", "state": "on", "attributes": {}},
        {"entity_id": "climate.ac", "state": "off",
         "attributes": {"temperature": 24.0, "current_temperature": None}},
        {"entity_id": "weather.home", "state": "partlycloudy",
         "attributes": {"temperature": 14.0, "temperature_unit": "°C", "humidity": 74}},
        {"entity_id": "sensor.bedroom_temp", "state": "22.5",
         "attributes": {"device_class": "temperature", "unit_of_measurement": "°C",
                        "friendly_name": "卧室温度"}},
        {"entity_id": "switch.hidden_sub", "state": "on", "attributes": {}},  # 不在目录 → 不渲染
        "garbage",  # 畸形 → 跳过
    ]


def test_renders_curated_devices_only_sorted():
    out = build_context(_states(), _registry())
    assert "- climate.ac: off,目标 24.0°" in out
    assert "- light.a: on" in out
    assert "switch.hidden_sub" not in out
    # 设备行按 id 排序:climate 在 light 前
    assert out.index("climate.ac") < out.index("light.a")


def test_climate_room_temp_omitted_when_none():
    out = build_context(_states(), _registry())
    assert "室温" not in out.split("\n")[0]  # current_temperature=None → 不渲染室温段


def test_weather_and_sensor_lines():
    out = build_context(_states(), _registry())
    assert "- 室外(weather.home): partlycloudy,14.0°C,湿度 74%" in out
    assert "- 卧室温度: 22.5 °C" in out


def test_missing_environment_degrades():
    states = [{"entity_id": "light.a", "state": "off", "attributes": {}}]
    out = build_context(states, _registry())
    assert "室外" not in out and "光" not in out
    assert "- light.a: off" in out


def test_climate_room_temp_rendered_when_present():
    states = [{"entity_id": "climate.ac", "state": "cool",
               "attributes": {"temperature": 26, "current_temperature": 28.5}}]
    out = build_context(states, _registry())
    assert "- climate.ac: cool,目标 26°,室温 28.5°" in out

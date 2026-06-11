import asyncio
import threading
from enum import Enum
from types import SimpleNamespace

from custom_components.janus.bridge import (
    HassServiceCaller,
    areas_from_registry,
    config_from_hass,
    devices_from_registry,
    entities_from_registry,
    services_from_hass,
    states_from_hass,
)


class _Cat(Enum):  # 模拟 HA 的 EntityCategory 枚举
    CONFIG = "config"


def test_states_from_hass():
    s = SimpleNamespace(entity_id="light.a", attributes={"friendly_name": "主灯"})
    assert states_from_hass([s]) == [{"entity_id": "light.a",
                                      "attributes": {"friendly_name": "主灯"}}]


def test_services_from_hass():
    out = services_from_hass({"light": {"turn_on": object(), "turn_off": object()}})
    assert out == [{"domain": "light", "services": {"turn_on": {}, "turn_off": {}}}]


def test_entities_from_registry_enum_category_to_str():
    e1 = SimpleNamespace(entity_id="light.ind", device_id="d1", area_id=None,
                         entity_category=_Cat.CONFIG)
    e2 = SimpleNamespace(entity_id="light.a", device_id="d1", area_id="a1",
                         entity_category=None)
    out = entities_from_registry([e1, e2])
    assert out[0]["entity_category"] == "config"
    assert out[1] == {"entity_id": "light.a", "device_id": "d1",
                      "area_id": "a1", "entity_category": None}


def test_devices_from_registry_sets_to_lists():
    d = SimpleNamespace(id="d1", area_id="a1",
                        identifiers={("xiaomi_miot", "MAC-CE1")},
                        config_entries={"CE1"},
                        name_by_user=None, name="空调插座")
    out = devices_from_registry([d])
    assert out == [{"id": "d1", "area_id": "a1",
                    "identifiers": [["xiaomi_miot", "MAC-CE1"]],
                    "config_entries": ["CE1"], "name": "空调插座"}]


def test_areas_from_registry():
    a = SimpleNamespace(id="a1", name="卧室")
    assert areas_from_registry([a]) == [{"area_id": "a1", "name": "卧室"}]


def test_config_from_hass():
    assert config_from_hass("°F") == {"unit_system": {"temperature": "°F"}}


def test_converters_feed_existing_pure_logic_end_to_end():
    """组合验证:bridge 输出直接喂 build_registry_snapshot + Registry.from_ha。"""
    from gatekeeper.ha_mapping import build_registry_snapshot
    from gatekeeper.registry import Registry

    states = states_from_hass([
        SimpleNamespace(entity_id="light.a", attributes={"friendly_name": "主灯"}),
        SimpleNamespace(entity_id="switch.cam_wm", attributes={"friendly_name": "水印"}),
    ])
    services = services_from_hass({"light": {"turn_on": 0, "turn_off": 0},
                                   "switch": {"turn_on": 0, "turn_off": 0}})
    entities = entities_from_registry([
        SimpleNamespace(entity_id="light.a", device_id="dl", area_id="a1", entity_category=None),
        SimpleNamespace(entity_id="switch.cam_wm", device_id="dc", area_id=None, entity_category=None),
        SimpleNamespace(entity_id="camera.cam", device_id="dc", area_id=None, entity_category=None),
    ])
    devices = devices_from_registry([
        SimpleNamespace(id="dl", area_id="a1", identifiers={("m", "L")},
                        config_entries=set(), name_by_user=None, name="灯"),
        SimpleNamespace(id="dc", area_id=None, identifiers={("m", "C")},
                        config_entries=set(), name_by_user=None, name="摄像机"),
    ])
    areas = areas_from_registry([SimpleNamespace(id="a1", name="卧室")])
    snap = build_registry_snapshot(entities, devices, areas, config=config_from_hass("°C"))
    reg = Registry.from_ha(states, services, snapshot=snap)
    d = reg.get("light.a")
    assert d is not None and d.area == "卧室"          # area join 生效
    assert reg.get("switch.cam_wm") is None            # 从属开关被策展(camera 主域兄弟)


def test_hass_service_caller_round_trip():
    calls = []

    class FakeServices:
        async def async_call(self, domain, service, data, blocking=True):
            calls.append((domain, service, data, blocking))

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    hass = SimpleNamespace(services=FakeServices(), loop=loop)
    HassServiceCaller(hass).call_service("light", "turn_on", "light.a", {"brightness_pct": 50})
    loop.call_soon_threadsafe(loop.stop)
    assert calls == [("light", "turn_on",
                      {"entity_id": "light.a", "brightness_pct": 50}, True)]

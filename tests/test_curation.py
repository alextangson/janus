from gatekeeper.curation import _hardware_keys, _dedup
from gatekeeper.ha_mapping import build_registry_snapshot
from gatekeeper.models import Device


def _dev(type_="switch", device_id=None, cat=None, name="x"):
    return Device(name=name, type=type_, area="", entity_category=cat, device_id=device_id)


def test_hardware_keys_strips_config_entry_suffix():
    entry = {"id": "d1",
             "identifiers": [["xiaomi_miot", "dc:ed:83:a1:bb:c3-01KT8ADFRAK2HPZMB6RTHA3BXT"]],
             "config_entries": ["01KT8ADFRAK2HPZMB6RTHA3BXT"]}
    assert _hardware_keys(entry) == [("xiaomi_miot", "dc:ed:83:a1:bb:c3")]


def test_hardware_keys_value_without_matching_suffix_kept_as_is():
    entry = {"id": "d1", "identifiers": [["hue", "abc-123"]], "config_entries": ["zzz"]}
    assert _hardware_keys(entry) == [("hue", "abc-123")]


def test_hardware_keys_malformed_identifiers_skipped():
    entry = {"id": "d1",
             "identifiers": ["garbage", ["only-one"], ["ok", 5]],
             "config_entries": []}
    assert _hardware_keys(entry) == []


def test_hardware_keys_missing_fields_empty():
    assert _hardware_keys({}) == []


def test_dedup_drops_mirror_keeps_unsuffixed_representative():
    snap = build_registry_snapshot([], [
        {"id": "devA", "identifiers": [["xm", "MAC-CE1"]], "config_entries": ["CE1"]},
        {"id": "devB", "identifiers": [["xm", "MAC-CE2"]], "config_entries": ["CE2"]},
        {"id": "devC", "identifiers": [["xm", "OTHER"]], "config_entries": []},
        {"id": "devD"},  # 无 identifiers → 不参与去重
    ], [])
    devices = {
        "switch.x_alarm": _dev(device_id="devA"),
        "switch.x_alarm_2": _dev(device_id="devB"),   # 镜像:实体带 _2 后缀
        "switch.y": _dev(device_id="devC"),
        "switch.z": _dev(device_id="devD"),
        "switch.standalone": _dev(device_id=None),    # 无设备 → 不受影响
    }
    out = _dedup(devices, snap)
    assert set(out) == {"switch.x_alarm", "switch.y", "switch.z", "switch.standalone"}


def test_dedup_tie_breaks_by_device_id_order():
    snap = build_registry_snapshot([], [
        {"id": "devB", "identifiers": [["xm", "MAC-CE2"]], "config_entries": ["CE2"]},
        {"id": "devA", "identifiers": [["xm", "MAC-CE1"]], "config_entries": ["CE1"]},
    ], [])
    devices = {
        "switch.p": _dev(device_id="devB"),
        "switch.q": _dev(device_id="devA"),
    }
    out = _dedup(devices, snap)
    assert set(out) == {"switch.q"}  # 后缀数平手 → device id 字典序最小者(devA)胜


def test_dedup_device_not_in_registry_untouched():
    snap = build_registry_snapshot([], [], [])
    devices = {"switch.a": _dev(device_id="ghost")}
    assert set(_dedup(devices, snap)) == {"switch.a"}

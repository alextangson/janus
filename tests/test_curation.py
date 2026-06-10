from gatekeeper.curation import _hardware_keys, _dedup, _prune, curate
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


def _prune_snapshot():
    entities = [
        # 摄像机:camera 主域 + 子功能开关 + config 指示灯
        {"entity_id": "camera.cam_video", "device_id": "cam"},
        {"entity_id": "switch.cam_watermark", "device_id": "cam"},
        {"entity_id": "light.cam_indicator", "device_id": "cam", "entity_category": "config"},
        # 插座:只有 switch(+sensor 读数)→ switch 即设备
        {"entity_id": "switch.plug_power", "device_id": "plug"},
        {"entity_id": "sensor.plug_energy", "device_id": "plug"},
        # 空调插座:climate 主域 + 摆风开关
        {"entity_id": "climate.acp_ac", "device_id": "acp"},
        {"entity_id": "switch.acp_swing", "device_id": "acp"},
        # 灯条:两个 light,非 switch 域互不压制
        {"entity_id": "light.bar_main", "device_id": "bar"},
        {"entity_id": "light.bar_ambient", "device_id": "bar"},
        # config 类别的主域兄弟不算数:switch 应保留
        {"entity_id": "light.cfg_indicator", "device_id": "cfgdev", "entity_category": "config"},
        {"entity_id": "switch.cfg_main", "device_id": "cfgdev"},
    ]
    devices = [{"id": i} for i in ("cam", "plug", "acp", "bar", "cfgdev")]
    return build_registry_snapshot(entities, devices, [])


def _prune_devices():
    return {
        "switch.cam_watermark": _dev(device_id="cam"),
        "light.cam_indicator": _dev(type_="light", device_id="cam", cat="config"),
        "switch.plug_power": _dev(device_id="plug"),
        "climate.acp_ac": _dev(type_="climate", device_id="acp"),
        "switch.acp_swing": _dev(device_id="acp"),
        "light.bar_main": _dev(type_="light", device_id="bar"),
        "light.bar_ambient": _dev(type_="light", device_id="bar"),
        "switch.cfg_main": _dev(device_id="cfgdev"),
    }


def test_prune_drops_config_category():
    out = _prune(_prune_devices(), _prune_snapshot())
    assert "light.cam_indicator" not in out


def test_prune_drops_subordinate_switch():
    out = _prune(_prune_devices(), _prune_snapshot())
    assert "switch.cam_watermark" not in out      # camera 主域
    assert "switch.acp_swing" not in out          # climate 主域


def test_prune_keeps_switch_only_device():
    out = _prune(_prune_devices(), _prune_snapshot())
    assert "switch.plug_power" in out             # sensor 兄弟不算主域


def test_prune_keeps_primary_domain_entities():
    out = _prune(_prune_devices(), _prune_snapshot())
    assert "climate.acp_ac" in out
    assert {"light.bar_main", "light.bar_ambient"} <= set(out)  # 非 switch 域互不压制


def test_prune_config_sibling_not_counted_as_primary():
    out = _prune(_prune_devices(), _prune_snapshot())
    assert "switch.cfg_main" in out               # 唯一主域兄弟是 config 指示灯 → 不算


def test_curate_composes_dedup_then_prune():
    snap = build_registry_snapshot(
        [
            {"entity_id": "camera.cam_video", "device_id": "devA"},
            {"entity_id": "switch.cam_wm", "device_id": "devA"},
            {"entity_id": "camera.cam_video_2", "device_id": "devB"},
            {"entity_id": "switch.cam_wm_2", "device_id": "devB"},
            {"entity_id": "switch.plug", "device_id": "devP"},
        ],
        [
            {"id": "devA", "identifiers": [["xm", "MAC-CE1"]], "config_entries": ["CE1"]},
            {"id": "devB", "identifiers": [["xm", "MAC-CE2"]], "config_entries": ["CE2"]},
            {"id": "devP", "identifiers": [["xm", "P"]], "config_entries": []},
        ],
        [],
    )
    devices = {
        "switch.cam_wm": _dev(device_id="devA"),
        "switch.cam_wm_2": _dev(device_id="devB"),
        "switch.plug": _dev(device_id="devP"),
    }
    out = curate(devices, snap)
    # 镜像 devB 被去重;devA 的水印开关被从属规则隐藏;插座保留
    assert set(out) == {"switch.plug"}

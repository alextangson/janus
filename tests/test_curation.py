from gatekeeper.curation import _hardware_keys


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

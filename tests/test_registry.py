def test_loads_eight_devices(registry):
    assert len(registry.device_ids()) == 8
    assert registry.get("lock.front_door").name == "大门门锁"
    assert registry.get("nope.nope") is None


def test_is_dangerous_is_per_operation(registry):
    assert registry.is_dangerous("lock.front_door", "unlock") is True
    assert registry.is_dangerous("lock.front_door", "lock") is False
    assert registry.is_dangerous("alarm_control_panel.home", "disarm") is True
    assert registry.is_dangerous("switch.gas_valve", "turn_off") is True
    assert registry.is_dangerous("light.living_room", "turn_on") is False
    assert registry.is_dangerous("ghost.device", "unlock") is False


def test_prompt_catalog_lists_devices_without_leaking_danger(registry):
    catalog = registry.as_prompt_catalog()
    assert "lock.front_door" in catalog
    assert "set_temperature" in catalog
    assert "16-30" in catalog
    # 危险标记绝不能进入给模型的清单——危险判断是代码的事
    assert "dangerous" not in catalog
    assert "危险" not in catalog

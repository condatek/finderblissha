"""BLISS1 timed overrides and the app's indefinite manual mode."""
import json
from datetime import datetime, timedelta

import pytest

from .conftest import bliss1_device, SERIAL
from custom_components.finderblissha.pyfinderbliss.device_parser import parse_device_data


@pytest.mark.parametrize("hours", [0, 1, 3])
async def test_setpoint_round_trips_in_selected_mode(make_api, hours):
    api, cloud = make_api(bliss1_device())
    api._bliss1_override_hours = hours
    await api.async_set_temperature(SERIAL, 18.3)
    settings = cloud.settings()
    parsed = parse_device_data({"devices": [cloud.device]})[0]
    assert parsed["mode"] == "manual"
    assert parsed["set_point"] == parsed["manual_set_point"] == 18.3
    if hours == 0:
        assert settings["mode"] == "MANUAL"
        assert settings["manualSetPoint"] == 183
        assert settings["manualSchedule"] == {
            "isOn": False, "start": None, "stop": None, "setPoint": None
        }
    else:
        assert settings["mode"] == "AUTO"
        schedule = settings["manualSchedule"]
        assert schedule["isOn"] and schedule["setPoint"] == 183
        assert datetime.fromisoformat(schedule["stop"]) - datetime.fromisoformat(schedule["start"]) == timedelta(hours=hours)


async def test_permanent_manual_mode_switch_and_back_to_schedule(make_api):
    api, cloud = make_api(bliss1_device())
    api._bliss1_override_hours = 0
    await api.async_set_mode(SERIAL, "MANUAL")
    assert cloud.settings()["mode"] == "MANUAL"
    await api.async_set_mode(SERIAL, "AUTO")
    assert cloud.settings()["mode"] == "AUTO"
    assert not cloud.settings()["manualSchedule"]["isOn"]


def test_parser_reads_app_indefinite_manual():
    raw = bliss1_device()
    settings = json.loads(raw["settings"])
    settings.update(mode="MANUAL", manualSetPoint=189,
                    manualSchedule={"isOn": False, "start": None, "stop": None, "setPoint": None})
    raw["settings"] = json.dumps(settings)
    parsed = parse_device_data({"devices": [raw]})[0]
    assert parsed["mode"] == "manual"
    assert parsed["set_point"] == parsed["manual_set_point"] == 18.9


async def test_device_duration_preference_is_independent_and_updates_cached_device(make_api):
    api, cloud = make_api(bliss1_device())
    devices = await api.async_get_devices()
    api.set_bliss1_override_hours(SERIAL, 0)
    api.set_bliss1_override_hours("OTHER", 3)
    assert devices[0].bliss1_override_hours == 0
    assert api.bliss1_override_hours("OTHER") == 3
    assert api.bliss1_override_hours("UNCONFIGURED") == 1
    await api.async_set_temperature(SERIAL, 18.3)
    assert cloud.settings()["mode"] == "MANUAL"


async def test_duration_control_restores_zero_and_updates_only_one_device(make_api, monkeypatch):
    from types import SimpleNamespace
    from custom_components.finderblissha.number import Bliss1OverrideDuration
    api, _ = make_api(bliss1_device())
    devices = await api.async_get_devices()
    coordinator = SimpleNamespace(data=devices)
    entity = Bliss1OverrideDuration(coordinator, api, devices[0])
    async def restore():
        return SimpleNamespace(native_value=0)
    async def added(_self):
        pass
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
    monkeypatch.setattr(CoordinatorEntity, "async_added_to_hass", added)
    monkeypatch.setattr(entity, "async_get_last_number_data", restore)
    monkeypatch.setattr(entity, "async_write_ha_state", lambda: None)
    await entity.async_added_to_hass()
    assert entity.native_value == 0
    assert api.bliss1_override_hours(SERIAL) == 0
    await entity.async_set_native_value(4)
    assert api.bliss1_override_hours(SERIAL) == 4
    assert api.bliss1_override_hours("OTHER") == 1
    await entity.async_set_native_value(0)
    assert api.bliss1_override_hours(SERIAL) == 0


def test_active_override_is_cloud_state_not_preference():
    from custom_components.finderblissha.number import active_override
    from custom_components.finderblissha.pyfinderbliss.pyfinderbliss_wrapper import BlissDevice
    raw = bliss1_device()
    settings = json.loads(raw["settings"])
    settings.update(mode="MANUAL", manualSetPoint=189)
    raw["settings"] = json.dumps(settings)
    device = BlissDevice(parse_device_data({"devices": [raw]})[0], 3)
    assert active_override(device) == ("indefinite", 0)
    settings.update(mode="AUTO", manualSchedule={"isOn": True, "start": "2026-01-01T10:00:00", "stop": "2026-01-01T12:00:00"})
    device.settings = json.dumps(settings)
    assert active_override(device) == ("timed", 2)
    settings["manualSchedule"]["isOn"] = False
    device.settings = json.dumps(settings)
    assert active_override(device) == ("none", None)

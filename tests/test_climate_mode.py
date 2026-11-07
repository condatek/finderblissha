"""Cloud-confirmed mode and the device's delayed echo serve different purposes."""

import json
import time
from types import SimpleNamespace

import pytest
from homeassistant.components.climate import HVACMode

from custom_components.finderblissha.climate import FinderBlissClimate
from custom_components.finderblissha.pyfinderbliss.device_parser import parse_device_data
from custom_components.finderblissha.pyfinderbliss.pyfinderbliss_wrapper import BlissDevice

from .conftest import bliss1_device, bliss2_device


def climate_for(raw):
    device = BlissDevice(parse_device_data({"devices": [raw]})[0])
    coordinator = SimpleNamespace(data=[device], config_entry=None)
    return FinderBlissClimate(coordinator, None, device)


@pytest.mark.parametrize("setting,echo,expected", [
    ("OFF", 1, HVACMode.OFF),
    ("FROST", 1, HVACMode.OFF),
    ("AUTO", 0, HVACMode.HEAT),
    ("MANUAL", 0, HVACMode.HEAT),
    (None, 1, HVACMode.HEAT),
    (None, 0, HVACMode.OFF),
])
def test_confirmed_mode_takes_precedence_with_echo_fallback(setting, echo, expected):
    raw = bliss2_device(mode=setting)
    measures = json.loads(raw["measures"])
    measures["mode"] = echo
    raw["measures"] = json.dumps(measures)
    entity = climate_for(raw)
    assert entity.hvac_mode == expected
    assert entity.extra_state_attributes["operating_mode"] == (
        ("off" if setting == "FROST" else setting.lower())
        if setting is not None else ("auto" if echo == 1 else "off")
    )


def test_pending_mode_takes_precedence_until_cleared_or_expired():
    entity = climate_for(bliss2_device(mode="OFF"))
    entity._optimistic["mode"] = ("manual", time.monotonic() + 90)
    assert entity.hvac_mode == HVACMode.HEAT
    entity._optimistic.clear()
    assert entity.hvac_mode == HVACMode.OFF
    entity._optimistic["mode"] = ("manual", time.monotonic() - 1)
    assert entity.hvac_mode == HVACMode.OFF


def test_confirmed_summer_mode_still_resolves_to_cooling():
    raw = bliss2_device(extra_settings={"season": "SUMMER"})
    assert climate_for(raw).hvac_mode == HVACMode.COOL


@pytest.mark.parametrize("override", [False, True])
def test_bliss1_schedule_and_manual_override_still_show_heat(override):
    assert climate_for(bliss1_device(override=override)).hvac_mode == HVACMode.HEAT


def test_manual_target_uses_settings_while_hardware_still_reports_off():
    entity = climate_for(bliss2_device(mode="OFF", extra_settings={
        "primary": {"mode": "MANUAL", "manualSetPoint": {"value": 215}},
    }))
    assert entity.hvac_mode == HVACMode.HEAT
    assert entity.target_temperature == 21.5
    assert entity.extra_state_attributes["operating_mode"] == "manual"


def test_auto_target_uses_schedule_while_hardware_still_reports_off():
    raw = bliss2_device(mode="AUTO", days=[
        {"day": day, "setPoints": [{"hour": 0, "minute": 0, "setPoint": {"value": 175}}]}
        for day in range(1, 8)
    ])
    measures = json.loads(raw["measures"])
    measures["mode"] = 0
    raw["measures"] = json.dumps(measures)
    assert climate_for(raw).target_temperature == 17.5

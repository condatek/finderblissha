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

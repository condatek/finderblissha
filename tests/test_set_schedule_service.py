"""The finderblissha.set_schedule service on a real Home Assistant core."""

import json
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.finderblissha.const import DOMAIN
from custom_components.finderblissha.pyfinderbliss.schedule import build_schedule_days

from .conftest import APP_DAYS, FakeCloud, bliss2_device

ENTITY = "climate.living_room_thermostat"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
async def cloud(hass):
    fake = FakeCloud(bliss2_device(mode="OFF"))
    with patch(
        "custom_components.finderblissha.pyfinderbliss.pyfinderbliss_wrapper.BlissClientAsync",
        return_value=fake,
    ):
        entry = MockConfigEntry(domain=DOMAIN, data={"username": "user@example.com", "password": "not-a-password"})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield fake


async def call(hass, **data):
    await hass.services.async_call(DOMAIN, "set_schedule", {"entity_id": ENTITY, **data}, blocking=True)


async def test_service_is_registered(hass, cloud):
    assert hass.services.has_service(DOMAIN, "set_schedule")
    assert hass.states.get(ENTITY) is not None


async def test_all_day_17_writes_schedule_then_auto(hass, cloud):
    await call(hass, blocks=[{"from": "00:00", "to": "24:00", "temp": 17}])

    assert len(cloud.sent) == 2
    first, second = (json.loads(p["settings"]) for p in cloud.sent)
    assert first["automaticSchedule"]["days"] == build_schedule_days(
        blocks=[{"from": "00:00", "to": "24:00", "temp": 17}])
    assert first["primary"]["mode"] == "OFF"
    assert second["primary"]["mode"] == "AUTO"
    assert cloud.settings()["automaticSchedule"]["days"][0]["setPoints"] == [
        {"hour": 0, "minute": 0, "setPoint": 170}]
    # operating_mode follows the thermostat's own echo (measures), which only
    # moves when it next checks in; the commanded side is what was verified.


async def test_repeating_the_call_sends_nothing(hass, cloud):
    blocks = [{"from": "00:00", "to": "24:00", "temp": 15}]
    await call(hass, blocks=blocks)
    sent = len(cloud.sent)
    await call(hass, blocks=blocks)
    assert len(cloud.sent) == sent


async def test_occupied_per_day(hass, cloud):
    occupied = [
        {"from": "00:00", "to": "05:00", "temp": 19},
        {"from": "05:00", "to": "22:00", "temp": 20},
        {"from": "22:00", "to": "24:00", "temp": 19},
    ]
    await call(hass, days={d: occupied for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})
    assert cloud.settings()["automaticSchedule"]["days"] == APP_DAYS
    assert cloud.settings()["primary"]["mode"] == "AUTO"


async def test_bad_blocks_are_a_validation_error_and_send_nothing(hass, cloud):
    with pytest.raises(ServiceValidationError, match="24:00"):
        await call(hass, blocks=[{"from": "00:00", "to": "12:00", "temp": 17}])
    with pytest.raises(ServiceValidationError, match="either"):
        await call(hass)
    assert cloud.sent == []


async def test_a_dropped_write_fails_the_call(hass, cloud):
    cloud.apply_writes = False
    with pytest.raises(HomeAssistantError, match="did not apply"):
        await call(hass, blocks=[{"from": "00:00", "to": "24:00", "temp": 17}])
    # The mode was never sent: the schedule write failed first.
    assert all(json_mode(p) == "OFF" for p in cloud.sent)


def json_mode(payload):
    return json.loads(payload["settings"])["primary"]["mode"]

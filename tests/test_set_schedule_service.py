"""The finderblissha.set_schedule service on a real Home Assistant core."""

import json
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.finderblissha.const import DOMAIN
from custom_components.finderblissha.pyfinderbliss.schedule import build_schedule_days

from .conftest import APP_DAYS_BLISS2, FakeCloud, as_bliss2, bliss2_device

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


async def test_confirmed_off_survives_stale_auto_echo_and_refresh(hass, cloud):
    measures = json.loads(cloud.device["measures"])
    measures["mode"] = 1
    cloud.device["measures"] = json.dumps(measures)
    settings = cloud.settings()
    settings["primary"]["mode"] = "AUTO"
    cloud.device["settings"] = json.dumps(settings)
    coordinator = next(iter(hass.data[DOMAIN].values()))["coordinator"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "heat"

    await hass.services.async_call("climate", "set_hvac_mode", {
        "entity_id": ENTITY, "hvac_mode": "off",
    }, blocking=True)
    assert cloud.settings()["primary"]["mode"] == "OFF"
    assert hass.states.get(ENTITY).state == "off"
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.state == "off"
    assert state.attributes["temperature"] == 5.0
    assert state.attributes["operating_mode"] == "off"


async def test_failed_off_command_restores_confirmed_mode(hass, cloud):
    await call(hass, blocks=[{"from": "00:00", "to": "24:00", "temp": 17}])
    cloud.apply_writes = False
    with pytest.raises(HomeAssistantError, match="confirmation timed out"):
        await hass.services.async_call("climate", "set_hvac_mode", {
            "entity_id": ENTITY, "hvac_mode": "off",
        }, blocking=True)
    assert cloud.settings()["primary"]["mode"] == "AUTO"
    assert hass.states.get(ENTITY).state == "heat"


async def test_all_day_17_writes_schedule_then_auto(hass, cloud):
    await call(hass, blocks=[{"from": "00:00", "to": "24:00", "temp": 17}])

    assert len(cloud.sent) == 2
    first, second = (json.loads(p["settings"]) for p in cloud.sent)
    assert first["automaticSchedule"]["days"] == as_bliss2(build_schedule_days(
        blocks=[{"from": "00:00", "to": "24:00", "temp": 17}]))
    assert first["primary"]["mode"] == "OFF"
    assert second["primary"]["mode"] == "AUTO"
    assert cloud.settings()["automaticSchedule"]["days"][0]["setPoints"] == [
        {"hour": 0, "minute": 0, "setPoint": {"unit": "C", "value": 170}}]
    # Mode and target follow confirmed cloud settings while hardware catches up.


async def test_repeating_the_call_sends_nothing(hass, cloud):
    blocks = [{"from": "00:00", "to": "24:00", "temp": 15}]
    await call(hass, blocks=blocks)
    sent = len(cloud.sent)
    await call(hass, blocks=blocks)
    assert len(cloud.sent) == sent


@pytest.mark.parametrize("change", ["mode", "schedule", "both"])
async def test_repeated_service_restores_changes_made_through_finder(hass, cloud, change):
    blocks = [{"from": "00:00", "to": "24:00", "temp": 17}]
    await call(hass, blocks=blocks)
    sent = len(cloud.sent)
    settings = cloud.settings()
    if change in ("mode", "both"):
        settings["primary"]["mode"] = "OFF"
    if change in ("schedule", "both"):
        settings["automaticSchedule"]["days"] = APP_DAYS_BLISS2
    cloud.device["settings"] = json.dumps(settings)
    cloud.device["syncVersion"] += 1

    await call(hass, blocks=blocks)
    assert len(cloud.sent) == sent + (2 if change == "both" else 1)
    assert cloud.settings()["primary"]["mode"] == "AUTO"
    assert cloud.settings()["automaticSchedule"]["days"] == as_bliss2(
        build_schedule_days(blocks=blocks)
    )


async def test_identical_schedule_on_a_bliss2_sends_nothing_from_auto(hass, cloud):
    # Device reports dict set points; the same blocks must be a no-op once in AUTO.
    occupied = [
        {"from": "00:00", "to": "05:00", "temp": 19},
        {"from": "05:00", "to": "22:00", "temp": 20},
        {"from": "22:00", "to": "24:00", "temp": 19},
    ]
    await call(hass, blocks=occupied)
    assert len(cloud.sent) == 1  # only AUTO: the device was OFF, the schedule already matched
    sent = len(cloud.sent)
    await call(hass, blocks=occupied)
    assert len(cloud.sent) == sent


async def test_target_temperature_follows_a_dict_shaped_schedule(hass, cloud):
    await call(hass, blocks=[{"from": "00:00", "to": "24:00", "temp": 17}])
    # The thermostat checks in: its own echo now reports AUTO.
    measures = json.loads(cloud.device["measures"])
    measures["mode"] = 1
    cloud.device["measures"] = json.dumps(measures)
    entry_data = next(iter(hass.data[DOMAIN].values()))
    await entry_data["coordinator"].async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["temperature"] == 17.0


async def test_occupied_per_day(hass, cloud):
    occupied = [
        {"from": "00:00", "to": "05:00", "temp": 19},
        {"from": "05:00", "to": "22:00", "temp": 20},
        {"from": "22:00", "to": "24:00", "temp": 19},
    ]
    await call(hass, days={d: occupied for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})
    assert cloud.settings()["automaticSchedule"]["days"] == APP_DAYS_BLISS2
    assert cloud.settings()["primary"]["mode"] == "AUTO"


async def test_bad_blocks_are_a_validation_error_and_send_nothing(hass, cloud):
    with pytest.raises(ServiceValidationError, match="24:00"):
        await call(hass, blocks=[{"from": "00:00", "to": "12:00", "temp": 17}])
    with pytest.raises(ServiceValidationError, match="either"):
        await call(hass)
    assert cloud.sent == []


async def test_a_dropped_write_fails_the_call(hass, cloud):
    cloud.apply_writes = False
    with pytest.raises(HomeAssistantError, match="confirmation timed out"):
        await call(hass, blocks=[{"from": "00:00", "to": "24:00", "temp": 17}])
    # The mode was never sent: the schedule write failed first.
    assert all(json_mode(p) == "OFF" for p in cloud.sent)


async def test_schedule_written_but_auto_dropped_fails_and_a_retry_completes(hass, cloud):
    blocks = [{"from": "00:00", "to": "24:00", "temp": 17}]
    cloud.drop_if = lambda settings: settings["primary"]["mode"] == "AUTO"
    with pytest.raises(HomeAssistantError, match="confirmation timed out"):
        await call(hass, blocks=blocks)
    # The schedule landed; the thermostat keeps its previous mode.
    assert cloud.settings()["automaticSchedule"]["days"][0]["setPoints"][0]["setPoint"]["value"] == 170
    assert cloud.settings()["primary"]["mode"] == "OFF"

    cloud.drop_if = None
    sent = len(cloud.sent)
    await call(hass, blocks=blocks)
    # Retry skips the schedule (already there) and sends only AUTO.
    assert len(cloud.sent) == sent + 1
    assert cloud.settings()["primary"]["mode"] == "AUTO"


def json_mode(payload):
    return json.loads(payload["settings"])["primary"]["mode"]


async def test_bliss2_battery_and_voltage_sensors(hass, cloud):
    assert hass.states.get("sensor.living_room_battery").state == "25"
    voltage = hass.states.get("sensor.living_room_battery_voltage")
    assert float(voltage.state) == pytest.approx(3.8)
    assert voltage.attributes["unit_of_measurement"] == "V"
    assert "state_class" not in voltage.attributes


async def test_bliss2_implausible_battery_reading_is_unknown(hass, cloud):
    measures = json.loads(cloud.device["measures"])
    measures["batteryLevel"] = {"value": 100}
    cloud.device["measures"] = json.dumps(measures)
    entry_data = next(iter(hass.data[DOMAIN].values()))
    await entry_data["coordinator"].async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.living_room_battery").state == "unknown"
    assert float(hass.states.get("sensor.living_room_battery_voltage").state) == pytest.approx(10.0)


async def test_temperature_from_off_is_one_atomic_write(hass, cloud):
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": ENTITY, "temperature": 21}, blocking=True,
    )
    assert len(cloud.sent) == 1
    assert cloud.settings()["primary"]["mode"] == "MANUAL"
    state = hass.states.get(ENTITY)
    assert state.state == "heat"
    assert state.attributes["temperature"] == 21
    assert state.attributes["operating_mode"] == "manual"
    # The hardware echo remains OFF; a later poll must preserve the cloud setting.
    entry_data = next(iter(hass.data[DOMAIN].values()))
    await entry_data["coordinator"].async_refresh()
    assert hass.states.get(ENTITY).attributes["temperature"] == 21

"""BLISS2 liveness is based on thermostat check-ins, independently of cloud polling."""

from types import SimpleNamespace

import pytest

from custom_components.finderblissha.climate import FinderBlissClimate
from custom_components.finderblissha.pyfinderbliss import pyfinderbliss_wrapper
from custom_components.finderblissha.pyfinderbliss.device_parser import determine_bliss2_mode, parse_device_data
from custom_components.finderblissha.select import FinderBlissUpdateProfileSelect
from custom_components.finderblissha.sensor import FinderBlissScheduleSensor, FinderBlissTemperatureSensor

from .conftest import SERIAL, bliss1_device, bliss2_device


@pytest.fixture
def clock(monkeypatch):
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(pyfinderbliss_wrapper, "time", SimpleNamespace(monotonic=lambda: clock.now))
    return clock


@pytest.mark.parametrize(("code", "mode"), [(0, "off"), (1, "auto"), (2, "manual"), (3, "manual")])
def test_bliss2_reported_modes(code, mode):
    assert determine_bliss2_mode({"mode": code}) == mode


async def test_bliss2_check_in_and_write_liveness(make_api, clock):
    api, cloud = make_api({**bliss2_device(), "status": "SYNCHED"})
    assert (await api.async_get_devices())[0].online

    clock.now = 10 * 60
    cloud.device["syncVersion"] += 1
    assert (await api.async_get_devices())[0].online

    clock.now = 34 * 60
    devices = await api.async_set_temperature(SERIAL, 21.5)
    assert devices[0].online
    assert len(cloud.sent) == 1

    clock.now = 35 * 60
    assert not (await api.async_get_devices())[0].online

    cloud.device["syncVersion"] += 1
    assert (await api.async_get_devices())[0].online


async def test_missing_and_older_snapshots_cannot_refresh_check_in(make_api, clock, monkeypatch):
    api, cloud = make_api(bliss2_device())
    assert (await api.async_get_devices())[0].online

    clock.now = 24 * 60
    cloud.device["syncVersion"] -= 1
    assert (await api.async_get_devices())[0].online

    async def partial_response():
        return parse_device_data({"devices": [
            {**bliss2_device(), "serialNumber": "TEST0002"},
        ]})

    clock.now = 25 * 60
    monkeypatch.setattr(cloud, "get_devices", partial_response)
    devices = {device.serial_number: device for device in await api.async_get_devices()}
    assert not devices[SERIAL].online
    assert devices["TEST0002"].online


async def test_cloud_error_and_coordinator_availability(make_api):
    api, cloud = make_api({**bliss2_device(), "status": "ERROR-SUBGHZ"})
    device, = await api.async_get_devices()
    assert device.status == "OFF"
    assert device.cloud_status == "ERROR-SUBGHZ"
    coordinator = SimpleNamespace(data=[device], config_entry=None, last_update_success=True)
    entities = [
        FinderBlissClimate(coordinator, api, device),
        FinderBlissTemperatureSensor(coordinator, device),
        FinderBlissScheduleSensor(coordinator, device),
        FinderBlissUpdateProfileSelect(coordinator, api, device),
    ]
    assert all(not entity.available for entity in entities)

    cloud.device["status"] = "SYNCHED"
    cloud.device["syncVersion"] += 1
    coordinator.data = await api.async_get_devices()
    assert all(entity.available for entity in entities)
    coordinator.last_update_success = False
    assert all(not entity.available for entity in entities)
    coordinator.last_update_success = True
    coordinator.data = []
    assert all(not entity.available for entity in entities)


async def test_bliss1_with_long_sync_profile_stays_available(make_api, clock):
    api, _ = make_api(bliss1_device())
    assert (await api.async_get_devices())[0].online
    clock.now = 30 * 60
    assert (await api.async_get_devices())[0].online

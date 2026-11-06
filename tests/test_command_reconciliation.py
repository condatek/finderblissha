"""Delayed cloud visibility must not replay writes or mutate published state."""

import asyncio
import copy
import json

import pytest

from custom_components.finderblissha.pyfinderbliss.client import BlissCommandError
from custom_components.finderblissha.pyfinderbliss.device_parser import parse_device_data
from custom_components.finderblissha.pyfinderbliss import pyfinderbliss_wrapper as wrapper
from .conftest import SERIAL, bliss2_device


@pytest.mark.parametrize("lost_ack", [False, True])
async def test_delayed_confirmation_sends_once_even_with_lost_ack(make_api, monkeypatch, lost_ack):
    api, cloud = make_api(bliss2_device(mode="OFF"))
    old = copy.deepcopy(cloud.device)
    original_send = cloud.send_operation
    reads = 0

    async def send(*args, **kwargs):
        await original_send(*args, **kwargs)
        if lost_ack:
            raise BlissCommandError("ACK timeout")

    async def read():
        nonlocal reads
        reads += 1
        raw = old if reads <= 4 else cloud.device
        return parse_device_data({"devices": [copy.deepcopy(raw)]})

    monkeypatch.setattr(cloud, "send_operation", send)
    monkeypatch.setattr(cloud, "get_devices", read)
    devices = await api.async_set_temperature(SERIAL, 21)
    assert reads == 5
    assert len(cloud.sent) == 1
    assert wrapper.commanded_mode(devices[0]) == "manual"
    assert devices[0].manual_set_point == 21


async def test_matching_temperature_in_wrong_mode_is_not_confirmation(make_api):
    api, cloud = make_api(bliss2_device(extra_settings={
        "primary": {"mode": "AUTO", "manualSetPoint": {"value": 210}},
    }))
    cloud.apply_writes = False
    with pytest.raises(BlissCommandError, match="may already have been applied"):
        await api.async_set_temperature(SERIAL, 21)
    assert len(cloud.sent) == 1


async def test_polls_wait_and_published_snapshot_is_not_mutated(make_api, monkeypatch):
    api, cloud = make_api(bliss2_device(mode="OFF"))
    published = await api.async_get_devices()
    sent = asyncio.Event()
    release = asyncio.Event()
    original_send = cloud.send_operation

    async def send(*args, **kwargs):
        await original_send(*args, **kwargs)
        sent.set()
        await release.wait()

    monkeypatch.setattr(cloud, "send_operation", send)
    command = asyncio.create_task(api.async_set_temperature(SERIAL, 21))
    await sent.wait()
    poll = asyncio.create_task(api.async_get_devices())
    await asyncio.sleep(0)
    assert not poll.done()
    assert published[0].mode == "off"
    assert json.loads(published[0].settings)["primary"]["mode"] == "OFF"
    release.set()
    confirmed, polled = await asyncio.gather(command, poll)
    assert confirmed[0].manual_set_point == polled[0].manual_set_point == 21
    assert published[0].mode == "off"


async def test_old_version_cannot_roll_back_confirmed_state(make_api):
    api, cloud = make_api(bliss2_device(mode="OFF"))
    old = copy.deepcopy(cloud.device)
    await api.async_set_temperature(SERIAL, 21)
    cloud.device = old
    devices = await api.async_get_devices()
    assert wrapper.commanded_mode(devices[0]) == "manual"
    assert devices[0].manual_set_point == 21
    assert api._snapshot_dirty


async def test_confirmation_has_overall_deadline(make_api, monkeypatch):
    api, cloud = make_api(bliss2_device())
    original_read = cloud.get_devices

    async def read():
        if cloud.sent:
            await asyncio.Future()
        return await original_read()

    monkeypatch.setattr(wrapper, "BLISS2_VERIFY_TIMEOUT", 0.02)
    monkeypatch.setattr(cloud, "get_devices", read)
    with pytest.raises(BlissCommandError, match="confirmation timed out"):
        await asyncio.wait_for(api.async_set_mode(SERIAL, "OFF"), 0.5)
    assert not api._command_lock.locked()
    assert len(cloud.sent) == 1

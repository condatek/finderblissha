import json

import pytest

from custom_components.finderblissha.pyfinderbliss.client import BlissCommandError
from custom_components.finderblissha.pyfinderbliss.schedule import build_schedule_days

from .conftest import APP_DAYS, APP_DAYS_BLISS2, SERIAL, as_bliss2, bliss1_device, bliss2_device

VACANT_17 = build_schedule_days(blocks=[{"from": "00:00", "to": "24:00", "temp": 17}])


async def test_writes_days_in_the_device_shape_and_keeps_other_settings(make_api):
    api, cloud = make_api(bliss2_device(extra_settings={"automaticSchedule": {"days": APP_DAYS_BLISS2, "keep": 1}}))
    devices = await api.async_set_automatic_schedule(SERIAL, VACANT_17)

    assert len(cloud.sent) == 1
    payload = cloud.sent[0]
    assert payload["serialNumber"] == SERIAL and payload["status"] == "PENDING"
    assert payload["syncVersion"] == 7
    sent = json.loads(payload["settings"])
    # BLISS2 set points go out as {"unit": "C", "value": n}, like the device reports them.
    assert sent["automaticSchedule"] == {"days": as_bliss2(VACANT_17), "keep": 1}
    # Everything else in settings goes back unchanged.
    before = json.loads(bliss2_device()["settings"])
    assert {k: v for k, v in sent.items() if k != "automaticSchedule"} == {
        k: v for k, v in before.items() if k != "automaticSchedule"
    }
    assert devices[0].automatic_schedule["days"] == as_bliss2(VACANT_17)


async def test_same_schedule_sends_nothing(make_api):
    api, cloud = make_api(bliss2_device())
    devices = await api.async_set_automatic_schedule(SERIAL, build_schedule_days(blocks=[
        {"from": "00:00", "to": "05:00", "temp": 19},
        {"from": "05:00", "to": "22:00", "temp": 20},
        {"from": "22:00", "to": "24:00", "temp": 19},
    ]))
    assert cloud.sent == []
    assert devices[0].serial_number == SERIAL


async def test_same_schedule_in_another_order_sends_nothing(make_api):
    shuffled = [{"day": d["day"], "setPoints": list(reversed(d["setPoints"]))} for d in reversed(APP_DAYS_BLISS2)]
    api, cloud = make_api(bliss2_device(days=shuffled))
    await api.async_set_automatic_schedule(SERIAL, APP_DAYS)
    assert cloud.sent == []


async def test_a_write_the_server_drops_is_retried_then_raised(make_api):
    api, cloud = make_api(bliss2_device())
    cloud.apply_writes = False
    with pytest.raises(BlissCommandError, match="did not apply"):
        await api.async_set_automatic_schedule(SERIAL, VACANT_17)
    assert len(cloud.sent) == 2


async def test_resume_schedule_sends_auto_from_off(make_api):
    api, cloud = make_api(bliss2_device(mode="OFF"))
    await api.async_resume_schedule(SERIAL)
    assert len(cloud.sent) == 1
    assert cloud.settings()["primary"] == {"mode": "AUTO", "manualSetPoint": None}


async def test_resume_schedule_is_a_no_op_when_already_auto(make_api):
    api, cloud = make_api(bliss2_device(mode="AUTO"))
    await api.async_resume_schedule(SERIAL)
    assert cloud.sent == []


async def test_resume_schedule_clears_a_pending_manual_timer(make_api):
    api, cloud = make_api(bliss2_device(mode="AUTO", extra_settings={"manualTimer": {"value": 190}}))
    await api.async_resume_schedule(SERIAL)
    assert len(cloud.sent) == 1
    assert "manualTimer" not in cloud.settings()


async def test_resume_schedule_with_a_pending_timer_fails_if_the_write_is_dropped(make_api):
    # primary.mode already reads AUTO, so only the timer shows the write was lost.
    api, cloud = make_api(bliss2_device(mode="AUTO", extra_settings={"manualTimer": {"value": 190}}))
    cloud.apply_writes = False
    with pytest.raises(BlissCommandError, match="did not apply"):
        await api.async_resume_schedule(SERIAL)
    assert len(cloud.sent) == 2


async def test_bliss1_override_in_progress_is_sent_auto(make_api):
    api, cloud = make_api(bliss1_device(override=True))
    await api.async_resume_schedule(SERIAL)
    assert len(cloud.sent) == 1
    assert cloud.settings()["mode"] == "AUTO"
    assert cloud.settings()["manualSchedule"]["isOn"] is False


async def test_bliss1_plain_auto_is_skipped(make_api):
    api, cloud = make_api(bliss1_device(override=False))
    await api.async_resume_schedule(SERIAL)
    assert cloud.sent == []


async def test_bliss1_schedule_write_keeps_other_settings(make_api):
    api, cloud = make_api(bliss1_device())
    await api.async_set_automatic_schedule(SERIAL, VACANT_17)
    sent = json.loads(cloud.sent[0]["settings"])
    before = json.loads(bliss1_device()["settings"])
    assert sent["automaticSchedule"] == {"days": VACANT_17}
    assert {k: v for k, v in sent.items() if k != "automaticSchedule"} == {
        k: v for k, v in before.items() if k != "automaticSchedule"
    }


async def test_bliss2_dict_set_points_equal_to_the_built_schedule_send_nothing(make_api):
    # The on-device failure of v0.5.7: the device reports {"unit": "C", "value": 190},
    # the builder makes 190, and the two must compare equal.
    api, cloud = make_api(bliss2_device(days=APP_DAYS_BLISS2))
    await api.async_set_automatic_schedule(SERIAL, APP_DAYS)
    assert cloud.sent == []


async def test_bliss2_set_point_template_keeps_extra_keys(make_api):
    days = [{"day": d["day"], "setPoints": [
        {**sp, "setPoint": {**sp["setPoint"], "preset": 1}} for sp in d["setPoints"]]} for d in APP_DAYS_BLISS2]
    api, cloud = make_api(bliss2_device(days=days))
    await api.async_set_automatic_schedule(SERIAL, VACANT_17)
    sp = cloud.settings()["automaticSchedule"]["days"][0]["setPoints"][0]["setPoint"]
    assert sp == {"unit": "C", "preset": 1, "value": 170}


async def test_bliss2_with_no_schedule_gets_the_bliss2_shape(make_api):
    api, cloud = make_api(bliss2_device(days=[]))
    await api.async_set_automatic_schedule(SERIAL, VACANT_17)
    assert cloud.settings()["automaticSchedule"]["days"] == as_bliss2(VACANT_17)


async def test_bliss1_integer_set_points_stay_integers(make_api):
    api, cloud = make_api(bliss1_device())
    await api.async_set_automatic_schedule(SERIAL, VACANT_17)
    assert cloud.settings()["automaticSchedule"]["days"] == VACANT_17

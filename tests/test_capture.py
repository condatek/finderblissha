import json
import logging

import pytest

from custom_components.finderblissha.pyfinderbliss import capture

from .conftest import bliss2_device


@pytest.fixture(autouse=True)
def fresh_capture():
    capture._last.clear()
    capture._labels.clear()
    logger = logging.getLogger(capture.CAPTURE_LOGGER_NAME)
    level = logger.level
    yield logger
    logger.setLevel(level)


def payload(device):
    return json.dumps({"devices": [device]})


def test_off_by_default_even_with_integration_debug(caplog):
    logging.getLogger("custom_components.finderblissha").setLevel(logging.DEBUG)
    try:
        with caplog.at_level(logging.DEBUG, logger="custom_components.finderblissha"):
            capture.on_sync(payload(bliss2_device()))
    finally:
        logging.getLogger("custom_components.finderblissha").setLevel(logging.NOTSET)
    assert not [r for r in caplog.records if r.name == capture.CAPTURE_LOGGER_NAME]


def test_initial_state_then_only_changes(caplog, fresh_capture):
    fresh_capture.setLevel(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger=capture.CAPTURE_LOGGER_NAME)
    device = bliss2_device()
    capture.on_sync(payload(device))
    first = caplog.records[-1].getMessage()
    assert "device1(BLISS2) initial state" in first
    assert 'settings.automaticSchedule.days[0].setPoints[1].setPoint.value = 200' in first
    assert 'settings.primary.mode = "AUTO"' in first

    settings = json.loads(device["settings"])
    settings["automaticSchedule"]["days"][0]["setPoints"][2]["minute"] = 30
    device["settings"] = json.dumps(settings)
    device["syncVersion"] = 8
    capture.on_sync(payload(device))
    changes = caplog.records[-1].getMessage()
    assert "settings.automaticSchedule.days[0].setPoints[2].minute: 0 -> 30" in changes
    assert "syncVersion: 7 -> 8" in changes
    assert "setPoints[1]" not in changes


def test_identifiers_and_account_data_are_redacted(caplog, fresh_capture):
    fresh_capture.setLevel(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger=capture.CAPTURE_LOGGER_NAME)
    device = bliss2_device(extra_settings={
        "wifi": {"ssid": "home-net", "macAddress": "aa:bb:cc:dd:ee:ff", "wifiPwd": "hunter22", "psk": "pskvalue1"},
        "contact": "someone@example.com",
        "ownerId": "0f8fad5b-d9cb-469f-a165-70867728950e",
    })
    capture.on_sync(payload(device))
    text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in ("TEST0001", "dev-handle-1", "house-1", "Living room", "home-net",
                   "aa:bb:cc", "someone@example.com", "0f8fad5b", "hunter22", "pskvalue1"):
        assert secret not in text
    assert "settings.wifi.ssid = <redacted>" in text
    # Measures are reduced to the command-relevant fields.
    assert "measures.temperature" not in text and "measures.mode = 1" in text
    assert "measures.batteryLevel.value = 38" in text


def test_send_and_answer(caplog, fresh_capture):
    fresh_capture.setLevel(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger=capture.CAPTURE_LOGGER_NAME)
    device = bliss2_device()
    capture.on_sync(payload(device))
    out = dict(device, status="PENDING")
    settings = json.loads(out["settings"])
    settings["primary"]["mode"] = "OFF"
    out["settings"] = json.dumps(settings)
    capture.on_send(out)
    sent = caplog.records[-1].getMessage()
    assert "capture send device1(BLISS2)" in sent
    assert 'settings.primary.mode: "AUTO" -> "OFF"' in sent
    assert 'status: (absent) -> "PENDING"' in sent

    capture.on_answer({"type": 1, "target": "SyncResponse", "arguments": [
        {"serverSyncVersion": 22702214185, "status": "ACTIVE", "serverPayload": "{...}",
         "clientId": "0f8fad5b-d9cb-469f-a165-70867728950e"}]})
    answer = caplog.records[-1].getMessage()
    assert "arguments[0].serverSyncVersion = 22702214185" in answer
    assert "arguments[0].serverPayload = <payload>" in answer
    assert "0f8fad5b" not in answer


def test_capture_never_raises(fresh_capture):
    fresh_capture.setLevel(logging.DEBUG)
    capture.on_sync("not json")
    capture.on_sync({"devices": "nope"})
    capture.on_answer({"arguments": None})


def test_identifier_shaped_keys_and_location_fields_are_redacted(caplog, fresh_capture):
    fresh_capture.setLevel(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger=capture.CAPTURE_LOGGER_NAME)
    device = bliss2_device(extra_settings={
        "linked": {"0f8fad5bd9cb469fa16570867728950e": {"on": True}, "someone@example.com": 1},
        "site": {"city": "Somewhere", "zipCode": "00000", "street": "1 Test Lane", "label": "Upstairs"},
    })
    capture.on_sync(payload(device))
    text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in ("0f8fad5b", "someone@example.com", "Somewhere", "00000", "Test Lane", "Upstairs", "Europe/Rome"):
        assert secret not in text
    assert "settings.linked.<opaque>.on = true" in text
    assert "tz = <redacted>" in text


def test_settings_come_before_long_schedule_lists(caplog, fresh_capture):
    fresh_capture.setLevel(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger=capture.CAPTURE_LOGGER_NAME)
    device = bliss2_device()
    device["schedules"] = json.dumps([{"days": [{"day": d, "setPoints": [{"hour": h, "minute": 0, "setPoint": 190}
                                                    for h in range(12)]} for d in range(1, 8)]}] * 3)
    capture.on_sync(payload(device))
    text = caplog.records[-1].getMessage()
    assert "more lines" in text
    assert "settings.automaticSchedule.days[6].setPoints[2].setPoint.value = 190" in text
    assert text.index("settings.") < text.index("schedules[")


def test_a_level_set_by_name_before_import_is_kept():
    import importlib

    logger = logging.getLogger(capture.CAPTURE_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    importlib.reload(capture)
    assert logger.level == logging.DEBUG
    logger.setLevel(logging.NOTSET)
    importlib.reload(capture)
    assert logger.level == logging.WARNING

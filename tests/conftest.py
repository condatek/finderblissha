"""Shared fixtures: a fake Finder cloud holding BLISS2 devices in the
SignalR sync payload shape that parse_device_data reads."""

import copy
import json

import pytest

from custom_components.finderblissha.pyfinderbliss import pyfinderbliss_wrapper
from custom_components.finderblissha.pyfinderbliss.device_parser import parse_device_data

SERIAL = "TEST0001"

# What the app's own schedule looks like on the device: 19 C 00-05,
# 20 C 05-22, 19 C 22-24 on every day.
APP_DAYS = [
    {"day": d, "setPoints": [
        {"hour": 0, "minute": 0, "setPoint": 190},
        {"hour": 5, "minute": 0, "setPoint": 200},
        {"hour": 22, "minute": 0, "setPoint": 190},
    ]}
    for d in range(1, 8)
]


def bliss2_device(mode="AUTO", days=None, extra_settings=None):
    """One device entry in the sync payload shape (settings/measures are JSON strings)."""
    settings = {
        "season": "WINTER",
        "updateStep": "60",
        "thermalDifferential": 3,
        "primary": {"mode": mode, "manualSetPoint": None},
        "automaticSchedule": {"days": copy.deepcopy(APP_DAYS if days is None else days)},
    }
    settings.update(extra_settings or {})
    measures = {
        "mode": 1 if mode == "AUTO" else 0,
        "status": "OFF",
        "temperature": {"value": 195, "unit": "C"},
        "humidity": {"value": 55},
        "setPoint": {"value": 200, "unit": "C"},
        "wifiLevel": 3,
        "batteryLevel": {"value": 29},
    }
    return {
        "handle": "dev-handle-1",
        "serialNumber": SERIAL,
        "name": "Living room",
        "tag": "BLISS2",
        "channel": 0,
        "role": "OWNER",
        "houseHandle": "house-1",
        "gatewayHandle": None,
        "isDeleted": False,
        "lastUpdate": "2026-10-30T05:00:00",
        "tz": "Europe/Rome",
        "syncVersion": 7,
        "settings": json.dumps(settings, separators=(",", ":")),
        "measures": json.dumps(measures, separators=(",", ":")),
        "schedules": "[]",
    }


class FakeCloud:
    """Stands in for BlissClientAsync: serves devices, records and applies writes."""

    def __init__(self, device):
        self.device = device
        self.sent = []
        self.apply_writes = True
        self.is_logged_in = True

    async def _login(self):
        self.is_logged_in = True

    async def get_devices(self):
        return parse_device_data({"devices": [copy.deepcopy(self.device)]})

    async def send_operation(self, device_data, operation_key="ALL"):
        self.sent.append(copy.deepcopy(device_data))
        if self.apply_writes:
            self.device["settings"] = device_data["settings"]
            self.device["syncVersion"] += 1

    async def reset_connection(self):
        pass

    async def close(self):
        pass

    def settings(self):
        return json.loads(self.device["settings"])


@pytest.fixture(autouse=True)
def no_command_delays(monkeypatch):
    monkeypatch.setattr(pyfinderbliss_wrapper, "COMMAND_VERIFY_DELAY", 0)
    monkeypatch.setattr(pyfinderbliss_wrapper, "COMMAND_RETRY_DELAY", 0)


@pytest.fixture
def make_api():
    def _make(device):
        cloud = FakeCloud(device)
        api = pyfinderbliss_wrapper.PyFinderBlissAPI("user@example.com", "not-a-password")
        api._client = cloud
        return api, cloud
    return _make

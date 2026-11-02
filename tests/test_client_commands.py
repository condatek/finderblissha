"""Exercise real command framing and ACK handling against a fake websocket."""

import asyncio
from collections import deque
import json

import aiohttp
import pytest

from custom_components.finderblissha.pyfinderbliss import client


ACK = {"type": 1, "target": "SyncResponse", "arguments": [{"serverSyncVersion": 8}]}
PING = {"type": 6}


class ScriptedSocket:
    closed = False

    def __init__(self, responses=(), *, keep_pinging=False):
        self.responses = deque(responses)
        self.keep_pinging = keep_pinging
        self.sent = []

    async def send_str(self, text):
        self.sent.append(json.loads(text.rstrip("\x1e")))

    async def receive(self):
        if self.responses:
            delay, frame = self.responses.popleft()
            await asyncio.sleep(delay)
            if isinstance(frame, Exception):
                raise frame
        elif self.keep_pinging:
            await asyncio.sleep(0.001)
            frame = PING
        else:
            await asyncio.Future()
        return aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, json.dumps(frame) + "\x1e", "")

    async def close(self):
        self.closed = True


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setattr(client, "ACK_DRAIN_TIMEOUT", 0.01)

    def make(responses=(), *, keep_pinging=False):
        api = client.BlissClientAsync("test", "test")
        socket = ScriptedSocket(responses, keep_pinging=keep_pinging)
        api._ws = socket
        return api, socket

    return make


async def test_ack_arriving_after_three_seconds_is_accepted(make_client):
    api, socket = make_client([(3.1, ACK)])
    await api.send_operation({"settings": {}, "tag": "BLISS2"})
    assert api._last_server_sync_version == 8
    assert len(socket.sent) == 1
    assert not socket.closed


async def test_ack_after_several_pings_is_accepted(make_client):
    api, socket = make_client([(0, PING)] * 5 + [(0, ACK)])
    await api.send_operation({"settings": {}, "tag": "BLISS2"})
    assert api._last_server_sync_version == 8
    assert len(socket.sent) == 1


@pytest.mark.parametrize("keep_pinging", [False, True])
async def test_missing_ack_has_a_fixed_deadline_and_resets_socket(make_client, monkeypatch, keep_pinging):
    monkeypatch.setattr(client, "BLISS1_ACK_TIMEOUT", 0.03)
    monkeypatch.setattr(client, "BLISS2_ACK_TIMEOUT", 0.03)
    api, socket = make_client(keep_pinging=keep_pinging)
    with pytest.raises(client.BlissCommandError, match="did not acknowledge"):
        await asyncio.wait_for(api.send_operation({}), timeout=0.5)
    assert socket.closed
    assert api._ws is None
    assert api._last_server_sync_version == 0


async def test_unrelated_frame_with_a_version_is_not_an_ack(make_client, monkeypatch):
    monkeypatch.setattr(client, "BLISS1_ACK_TIMEOUT", 0.03)
    frame = {**ACK, "target": "Unrelated"}
    api, socket = make_client([(0, frame)])
    with pytest.raises(client.BlissCommandError):
        await api.send_operation({})
    assert socket.closed
    assert api._last_server_sync_version == 0


async def test_connection_reset_before_ack_closes_socket(make_client):
    api, socket = make_client([(0, ConnectionResetError("Disconnected"))])
    with pytest.raises(ConnectionResetError):
        await api.send_operation({})
    assert socket.closed
    assert api._ws is None


async def test_follow_up_pings_cannot_hold_the_command_lock(make_client):
    api, socket = make_client([(0, ACK)], keep_pinging=True)
    await asyncio.wait_for(api.send_operation({}), timeout=0.5)
    assert api._last_server_sync_version == 8
    assert not api._ws_lock.locked()
    assert not socket.closed


async def test_bliss1_keeps_a_shorter_ack_budget(make_client, monkeypatch):
    monkeypatch.setattr(client, "BLISS1_ACK_TIMEOUT", 0.02)
    monkeypatch.setattr(client, "BLISS2_ACK_TIMEOUT", 0.15)
    api, socket = make_client([(0.05, ACK)])
    with pytest.raises(client.BlissCommandError, match="within 0.02 seconds"):
        await api.send_operation({"tag": "BLISS1"})
    assert socket.closed

    api, socket = make_client([(0.05, ACK)])
    await api.send_operation({"tag": "BLISS2"})
    assert not socket.closed
    assert api._last_server_sync_version == 8

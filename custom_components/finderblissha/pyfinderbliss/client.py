"""Async client for the Finder Bliss SignalR API."""

import asyncio
import datetime
import json
import logging
import uuid

import aiohttp

from .const import (
    BASE_URL,
    CLIENT_ID,
    GRANT_TYPE,
    LOGIN_ENDPOINT,
    NEGOTIATE_URL,
    PING_INTERVAL,
    SCOPE,
)
from .device_parser import parse_device_data

_LOGGER = logging.getLogger(__name__)


class BlissCommandError(Exception):
    """A command was not acknowledged, or not applied, by the Finder cloud."""


class BlissClientAsync:
    """Asynchronous client for the Finder Bliss API."""

    def __init__(self, username: str, password: str, debug: bool = False):
        self._username = username
        self._password = password
        self._session: aiohttp.ClientSession | None = None
        self._token = None
        self._client_id = str(uuid.uuid4())
        self._ws = None
        self._last_server_sync_version = 0
        self._debug = debug
        # A single websocket serves every device, so two callers arriving
        # together - a service call targeting two thermostats fans out to both
        # entities in parallel - would both sit in ws.receive() and aiohttp
        # raises "Concurrent call to receive() is not allowed". Every exchange
        # is serialised through this lock; the _-prefixed variants below are
        # the bodies that run with it already held.
        self._ws_lock = asyncio.Lock()

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            # Finder's auth server rejects aiohttp's default User-Agent.
            # See GitHub issue #4.
            self._session = aiohttp.ClientSession(headers={"User-Agent": "okhttp/4.9.3"})

    async def close(self):
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def reset_connection(self):
        """Reset only the websocket so the next operation reconnects cleanly."""
        async with self._ws_lock:
            await self._reset_connection()

    async def _reset_connection(self):
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None

    def _get_stamp(self):
        return datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="microseconds"
        ).replace('+00:00', 'Z')

    async def _login(self):
        await self._ensure_session()
        url = f"{BASE_URL}{LOGIN_ENDPOINT}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        payload = {
            "grant_type": GRANT_TYPE,
            "client_id": CLIENT_ID,
            "scope": SCOPE,
            "username": self._username,
            "password": self._password,
        }

        async with self._session.post(url, data=payload, headers=headers) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise Exception(f"Login failed ({resp.status}): {text}")

            data = await resp.json()
            self._token = data.get("access_token")
            if not self._token:
                raise Exception("Login succeeded but no access_token returned")

            _LOGGER.debug("Login successful, token acquired")

    async def _negotiate(self):
        if not self._token:
            await self._login()

        await self._ensure_session()
        headers = {"Authorization": f"Bearer {self._token}"}
        async with self._session.post(NEGOTIATE_URL, headers=headers) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise Exception(f"Negotiate failed ({resp.status}): {text}")
            return json.loads(text)

    async def _handle_message(self, msg: aiohttp.WSMessage):
        if msg.type == aiohttp.WSMsgType.TEXT:
            parsed_frames = []
            for frame in msg.data.split("\x1e"):
                if not frame.strip():
                    continue
                _LOGGER.debug("Server frame: %s", frame[:200])
                try:
                    data = json.loads(frame)
                    parsed_frames.append(data)
                except json.JSONDecodeError:
                    _LOGGER.warning("Failed to parse JSON frame")
            return parsed_frames
        elif msg.type == aiohttp.WSMsgType.CLOSE:
            raise ConnectionResetError("Server closed connection.")
        return []

    async def connect_ws(self):
        if not self._token:
            await self._login()
        await self._ensure_session()

        negotiation = await self._negotiate()
        connection_id = negotiation.get("connectionId")
        ws_url = f"wss://bliss.iot.findernet.com/_sync?id={connection_id}"
        headers = {"Authorization": f"Bearer {self._token}"}

        self._ws = await self._session.ws_connect(
            ws_url, headers=headers, heartbeat=PING_INTERVAL
        )
        _LOGGER.debug("WebSocket connection established")

        handshake_msg = json.dumps({"protocol": "json", "version": 1}) + "\x1e"
        await self._ws.send_str(handshake_msg)

        init_request = {
            "type": 1,
            "target": "InitRequest",
            "arguments": [
                {
                    "clientId": self._client_id,
                    "stamp": self._get_stamp(),
                    "clientPlatform": "Android/7.1.1",
                    "clientModel": "OnePlus/ONEPLUS A5000",
                    "clientBuild": "166",
                }
            ],
        }
        await self._ws.send_str(json.dumps(init_request) + "\x1e")

        while True:
            try:
                msg = await self._ws.receive()
                frames = await self._handle_message(msg)
                if any(f == {} for f in frames):
                    _LOGGER.debug("InitRequest acknowledged by server")
                    return
            except asyncio.TimeoutError:
                raise Exception("Timeout waiting for InitRequest acknowledgment.")

    async def get_devices(self, ws_timeout: int = 15, reconnect_attempts: int = 2):
        async with self._ws_lock:
            return await self._get_devices(ws_timeout, reconnect_attempts)

    async def _get_devices(self, ws_timeout: int = 15, reconnect_attempts: int = 2):
        sync_request = {
            "type": 1,
            "target": "SyncRequest",
            "arguments": [
                {
                    "clientId": self._client_id,
                    "clientOperationId": "00000000-0000-0000-0000-000000000000",
                    "clientSyncVersion": 0,
                    "serverSyncVersion": 0,
                    "stamp": self._get_stamp(),
                    "status": "SYNC",
                    "clientPayload": None,
                    "serverPayload": None,
                    "clientOperationKey": "ALL",
                    "userId": "00000000-0000-0000-0000-000000000000"
                }
            ],
        }

        last_error: Exception | None = None
        for attempt in range(reconnect_attempts + 1):
            if not self._ws or self._ws.closed:
                await self.connect_ws()

            try:
                await self._ws.send_str(json.dumps(sync_request) + "\x1e")

                while True:
                    msg = await asyncio.wait_for(self._ws.receive(), timeout=ws_timeout)
                    frames = await self._handle_message(msg)

                    for data in frames:
                        if data.get("target") in ("SyncRequest", "SyncResponse") and "arguments" in data:
                            for arg in data["arguments"]:
                                if "serverPayload" in arg and arg["serverPayload"] is not None:
                                    self._last_server_sync_version = arg.get("serverSyncVersion", 0)
                                    _LOGGER.debug(
                                        "Sync success, serverSyncVersion: %s",
                                        self._last_server_sync_version,
                                    )
                                    payload = arg["serverPayload"]
                                    return parse_device_data(payload)

            except (asyncio.TimeoutError, ConnectionResetError, aiohttp.ClientError) as err:
                last_error = err
                _LOGGER.warning(
                    "Device sync attempt %s/%s failed: %s. Resetting websocket and retrying.",
                    attempt + 1,
                    reconnect_attempts + 1,
                    err,
                )
                await self._reset_connection()

        if isinstance(last_error, asyncio.TimeoutError):
            raise Exception(f"Timeout waiting for serverPayload after {ws_timeout} seconds.") from last_error
        if isinstance(last_error, ConnectionResetError):
            raise Exception("Connection reset by server during device fetch.") from last_error
        raise Exception(f"Failed to fetch devices after websocket reconnect attempts: {last_error}")

    async def send_operation(self, device_data: dict, operation_key: str = "ALL", debug_responses: int = 3):
        async with self._ws_lock:
            await self._send_operation(device_data, operation_key, debug_responses)

    async def _send_operation(self, device_data: dict, operation_key: str = "ALL", debug_responses: int = 3):
        if not self._ws or self._ws.closed:
            _LOGGER.debug("WebSocket closed before send_operation, reconnecting")
            await self.connect_ws()
            # Resync to get a valid _last_server_sync_version for the new session
            await self._get_devices(ws_timeout=10)

        payload_to_send = dict(device_data)

        for key in ["settings", "measures", "schedules"]:
            if key in payload_to_send and isinstance(payload_to_send[key], (dict, list)):
                payload_to_send[key] = json.dumps(payload_to_send[key], separators=(',', ':'))
            elif key not in payload_to_send:
                payload_to_send[key] = "{}" if key in ("settings", "measures") else "[]"

        client_payload_string = json.dumps({"devices": [payload_to_send]}, separators=(',', ':'))

        sync_request_message = {
            "type": 1,
            "target": "SyncRequest",
            "arguments": [{
                "clientId": self._client_id,
                "clientOperationId": str(uuid.uuid4()),
                "clientOperationKey": operation_key,
                "clientSyncVersion": self._last_server_sync_version,
                "serverSyncVersion": 0,
                "clientPayload": client_payload_string,
                "serverPayload": None,
                "stamp": self._get_stamp(),
                "status": "ACTIVE",
            }]
        }

        await self._ws.send_str(json.dumps(sync_request_message) + "\x1e")

        new_version_received = False
        for i in range(debug_responses):
            try:
                msg = await asyncio.wait_for(self._ws.receive(), timeout=3)
                frames = await self._handle_message(msg)

                for data in frames:
                    if data.get("target") in ("SyncRequest", "SyncResponse") and "arguments" in data:
                        for arg in data["arguments"]:
                            if "serverSyncVersion" in arg:
                                self._last_server_sync_version = arg["serverSyncVersion"]
                                _LOGGER.debug(
                                    "Setter ACK, serverSyncVersion: %s",
                                    self._last_server_sync_version,
                                )
                                new_version_received = True
                                break
                        if new_version_received:
                            break
                if new_version_received:
                    break

            except asyncio.TimeoutError:
                if i == 0:
                    _LOGGER.debug("No immediate response from server after command")
                break
            except ConnectionResetError:
                raise Exception("Connection reset by server during command acknowledgement.")

        # Drain any follow-up messages the server sends after the ACK
        # (e.g. updated device data). If left in the buffer, the next
        # get_devices() call would pick them up as a partial response.
        # Runs on the un-acknowledged path too, so a failed command still
        # leaves a clean buffer for the retry.
        try:
            while True:
                msg = await asyncio.wait_for(self._ws.receive(), timeout=1)
                await self._handle_message(msg)
        except asyncio.TimeoutError:
            pass

        # An un-acknowledged command is a dropped one. Returning normally here
        # would report success for a write the server never took, which then
        # surfaces a poll or two later as the old value coming back - looking
        # exactly like somebody changed it by hand.
        if not new_version_received:
            raise BlissCommandError("Server did not acknowledge the command")

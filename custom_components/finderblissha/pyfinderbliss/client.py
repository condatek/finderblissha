# client.py
import aiohttp
import asyncio
import json
import uuid
import datetime

from .const import (
    BASE_URL,
    LOGIN_ENDPOINT,
    NEGOTIATE_URL,
    CLIENT_ID,
    SCOPE,
    GRANT_TYPE,
    PING_INTERVAL,
)
from .device_parser import parse_device_data


class BlissClientAsync:
    """
    Asynchronous client for the Finder Bliss API with full protocol debugging.
    """

    def __init__(self, username: str, password: str, debug: bool = False):
        self._username = username
        self._password = password
        self._session: aiohttp.ClientSession | None = None
        self._token = None
        self._client_id = str(uuid.uuid4()) 
        self._ws = None
        self._last_server_sync_version = 0
        self._debug = debug

    def _debug_print(self, *args, **kwargs):
        if self._debug:
            print(*args, **kwargs)

    async def _ensure_session(self):
        """Ensure aiohttp session is alive."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self):
        """Close WebSocket and HTTP session."""
        if self._ws and not self._ws.closed:
            await self._ws.close()
            self._debug_print("[WS] Connection closed.")
        if self._session and not self._session.closed:
            await self._session.close()

    def _get_stamp(self):
        """Generates the required ISO8601 UTC timestamp with fractional seconds."""
        return datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="microseconds"
        ).replace('+00:00', 'Z')

    async def _login(self):
        # ... (login logic remains the same)
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

            self._debug_print("[AUTH] Login successful, token acquired.")

    async def _negotiate(self):
        # ... (negotiate logic remains the same)
        if not self._token:
            await self._login()

        await self._ensure_session()
        headers = {"Authorization": f"Bearer {self._token}"}
        async with self._session.post(NEGOTIATE_URL, headers=headers) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise Exception(f"Negotiate failed ({resp.status}): {text}")
            return json.loads(text)

    # --- NEW MESSAGE HANDLER FOR DEBUGGING ---
    async def _handle_message(self, msg: aiohttp.WSMessage, ws_timeout: float | None = None):
        """
        Receives one message and processes all frames within it, logging them.
        Returns a list of parsed JSON objects (frames).
        """
        if msg.type == aiohttp.WSMsgType.TEXT:
            parsed_frames = []
            for frame in msg.data.split("\x1e"):
                if not frame.strip():
                    continue
                
                self._debug_print(f"\n[SERVER RAW FRAME] >>> {frame}")
                
                try:
                    data = json.loads(frame)
                    parsed_frames.append(data)
                except json.JSONDecodeError as e:
                    print(f"[SERVER ERROR] Failed to parse JSON frame: {e}")
            return parsed_frames
        
        elif msg.type == aiohttp.WSMsgType.PING:
            print("[SERVER PING] Received.")
        elif msg.type == aiohttp.WSMsgType.PONG:
            print("[SERVER PONG] Received.")
        elif msg.type == aiohttp.WSMsgType.CLOSE:
            print("[SERVER CLOSE] Received close signal.")
            raise ConnectionResetError("Server closed connection.")
        
        return []

    async def connect_ws(self):
        """Establish and persist the WebSocket connection, logging handshake."""
        if not self._token:
            await self._login()
        await self._ensure_session()
        
        negotiation = await self._negotiate()
        connection_id = negotiation.get("connectionId")
        ws_url = f"wss://bliss.iot.findernet.com/_sync?id={connection_id}"
        headers = {"Authorization": f"Bearer {self._token}"}
        
        self._debug_print(f"[WS] Connecting to: {ws_url}")
        self._ws = await self._session.ws_connect(
            ws_url, headers=headers, heartbeat=PING_INTERVAL
        )
        print(f"[WS] Connection established.")
        
        # Handshake: '{"protocol":"json","version":1}\x1e'
        handshake_msg = json.dumps({"protocol": "json", "version": 1}) + "\x1e"
        self._debug_print(f"[CLIENT SEND] Handshake: {handshake_msg.strip()}")
        await self._ws.send_str(handshake_msg)
        
        # InitRequest
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
        init_req_str = json.dumps(init_request) + "\x1e"
        self._debug_print(f"[CLIENT SEND] InitRequest: {init_req_str.strip()}")
        await self._ws.send_str(init_req_str)
        
        # Wait for ack (empty object)
        while True:
            try:
                msg = await self._ws.receive()
                frames = await self._handle_message(msg)
                
                if any(f == {} for f in frames):
                    print("[WS ACK] Initialisation acknowledged by server.")
                    return
            except asyncio.TimeoutError:
                raise Exception("Timeout waiting for InitRequest acknowledgment.")

    async def get_devices(self, ws_timeout: int = 15):
        """
        Send a Passive SyncRequest (SYNC mode) to request the full device list 
        and update the internal server sync version.
        """
        if not self._ws or self._ws.closed:
            await self.connect_ws()

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
        
        sync_req_str = json.dumps(sync_request) + "\x1e"
        self._debug_print(f"\n[CLIENT SEND] SyncRequest (GET DEVICES): {sync_req_str.strip()}")
        await self._ws.send_str(sync_req_str)
        
        try:
            while True:
                msg = await asyncio.wait_for(self._ws.receive(), timeout=ws_timeout)
                frames = await self._handle_message(msg)
                
                for data in frames:
                    # Look for the SyncResponse from the server
                    # WAS: if data.get("target") == "SyncResponse" and "arguments" in data:
                    # FIX: Check for SyncRequest, as seen in the logs
                    if data.get("target") in ("SyncRequest", "SyncResponse") and "arguments" in data: 
                        for arg in data["arguments"]:
                            if "serverPayload" in arg and arg["serverPayload"] is not None:
                                
                                # CRITICAL: Update the last received version
                                self._last_server_sync_version = arg.get("serverSyncVersion", 0)
                                print(f"[SYNC SUCCESS] ServerSyncVersion updated to: {self._last_server_sync_version}")

                                payload = arg["serverPayload"]
                                devices = parse_device_data(payload)
                                return devices
                                
        except asyncio.TimeoutError:
            raise Exception(f"Timeout waiting for serverPayload after {ws_timeout} seconds.")
        except ConnectionResetError:
            raise Exception("Connection reset by server during device fetch.")


    async def send_operation(self, device_data: dict, operation_key: str = "ALL", debug_responses: int = 3):
        """
        Sends an ACTIVE SyncRequest (Setter mode) to change a device's state.
        
        Args:
            device_data (dict): The device data containing 'handle', 'serialNumber', and 
                                the modified 'settings' (as a Python dict) and 
                                minimal 'measures'/'schedules' (as Python dict/list).
        """
        if not self._ws or self._ws.closed:
            raise RuntimeError("WebSocket not connected. Run get_devices first.")
        
        # 1. Prepare the payload: Ensure nested fields (settings, measures, schedules)
        #    are converted to JSON strings before the final outer wrapper.
        payload_to_send = dict(device_data) 

        # We must serialize nested dicts/lists into strings for the server's expected format.
        for key in ["settings", "measures", "schedules"]:
            if key in payload_to_send and isinstance(payload_to_send[key], (dict, list)):
                # Serialize the nested object into a minimal string
                payload_to_send[key] = json.dumps(payload_to_send[key], separators=(',', ':'))
            elif key not in payload_to_send:
                # Ensure minimal required fields are present if not provided by caller
                payload_to_send[key] = "{}" if key in ("settings", "measures") else "[]"
            
        # 2. Wrap the device in the final clientPayload string
        #    This is the outer JSON string for the 'clientPayload' field.
        client_payload_string = json.dumps({"devices": [payload_to_send]}, separators=(',', ':'))

        # 3. Construct the main SyncRequest message
        sync_request_message = {
            "type": 1,
            "target": "SyncRequest",
            "arguments": [{
                "clientId": self._client_id,
                "clientOperationId": str(uuid.uuid4()), # Dynamic UUID
                "clientOperationKey": operation_key,
                "clientSyncVersion": self._last_server_sync_version, # Critical: Use last version from SYNC
                "serverSyncVersion": 0,
                "clientPayload": client_payload_string, # The nested JSON string
                "serverPayload": None,
                "stamp": self._get_stamp(),
                "status": "ACTIVE", # Critical: ACTIVE mode for setters
            }]
        }
        
        sync_req_str = json.dumps(sync_request_message) + "\x1e"
        self._debug_print(f"\n[CLIENT SEND] SyncRequest (SETTER): {sync_req_str.strip()}")
        await self._ws.send_str(sync_req_str)

        # 4. Debug: print next few server responses and look for version update
        # ------------------- REPLACE THIS BLOCK ----------------------
        new_version_received = False
        for i in range(debug_responses):
            try:
                # Use a short timeout for waiting on command acknowledgement
                msg = await asyncio.wait_for(self._ws.receive(), timeout=3) 
                frames = await self._handle_message(msg)

                for data in frames:
                    # Look for the new serverSyncVersion in ANY incoming SyncRequest/SyncResponse
                    if data.get("target") in ("SyncRequest", "SyncResponse") and "arguments" in data:
                        for arg in data["arguments"]:
                            if "serverSyncVersion" in arg:
                                self._last_server_sync_version = arg["serverSyncVersion"]
                                print(f"[SETTER ACK] Updated serverSyncVersion: {self._last_server_sync_version}")
                                new_version_received = True
                                break # Found the version
                        if new_version_received:
                            break
                if new_version_received:
                    break # Break out of the for i in range(debug_responses) loop
                            
            except asyncio.TimeoutError:
                if i == 0:
                    print("No immediate response from server after command. Continuing wait...")
                break
            except ConnectionResetError:
                raise Exception("Connection reset by server during command acknowledgement.")
        # ------------------- END OF REPLACE BLOCK ----------------------
        
        # 5. CRITICAL STEP: Manually trigger a new SYNC request to get the device update
        # We need the full device payload, which requires calling get_devices 
        # using the newest self._last_server_sync_version.
        
        if new_version_received:
            print("Successfully received new sync version. Attempting device refresh...")
            # We already have a function for this, but we need to pass the version.
            # get_devices already uses the latest version (self._last_server_sync_version)
            try:
                # Use a shorter timeout as the server should respond quickly
                await self.get_devices(ws_timeout=5)
                print("[SETTER REFRESH] Device status refreshed successfully.")
            except Exception as e:
                print(f"[SETTER REFRESH FAIL] Could not refresh device status: {e}")
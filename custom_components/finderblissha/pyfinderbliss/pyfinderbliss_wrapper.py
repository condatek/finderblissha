import asyncio
import json
from typing import Union
from .client import BlissClientAsync

class BlissDevice:
    def __init__(self, device_data):
        self.handle = device_data.get("handle")
        self.name = device_data.get("name")
        self.temperature = device_data.get("temperature")
        self.humidity = device_data.get("humidity")
        self.set_point = device_data.get("set_point")  # match parser key
        self.manual_set_point = device_data.get("manual_set_point")  # match parser key
        self.mode = device_data.get("mode")
        self.mode_setting = device_data.get("mode_setting")  # add this too
        self.wifi_level = device_data.get("wifi_level")      # add this too
        self.battery_level = device_data.get("battery_level")
        self.status = device_data.get("status")
        self.serial_number = device_data.get("serial_number")
        self.model = device_data.get("model")
        self.raw = device_data
        
        # Add the CRITICAL SETTER METADATA fields (must match parser keys: snake_case)
        self.role = device_data.get("role")
        self.house_handle = device_data.get("house_handle")       
        self.gateway_handle = device_data.get("gateway_handle")
        self.is_deleted = device_data.get("is_deleted")
        self.tag = device_data.get("tag")              # FIX: Add tag (used for model/mode logic)
        self.channel = device_data.get("channel")      # Add channel if it's in your parser output

        # Add these lines:
        self.settings = device_data.get("settings", {})
        self.measures = device_data.get("measures", {})
        self.schedules = device_data.get("schedules", [])

    async def set_mode(self, mode: str):
        """
        Change device mode using the full protocol SyncRequest setter.
        Requires sending the entire device object with the desired setting changed.
        mode: 'OFF', 'AUTO', 'MANUAL', 'FROST', 'ECO' (must be uppercase)
        """
        mode = mode.upper()
        
        # Ensure the client is available
        if not hasattr(self, "_client") or self._client is None:
            raise Exception("Device client not initialized")

        # 1. Start with the CURRENT state and modify ONLY the necessary part
        # self.settings is a JSON string, so we must load it to modify it.
        settings_dict = json.loads(self.settings)
        
        # 2. Update the 'primary' object in settings
        if self.model in ["BLISS2", "BLISS-HA"]:
            # --- Your mode change logic is integrated here ---
            if mode in ["AUTO", "OFF", "FROST", "ECO"]:
                settings_dict["primary"] = {
                    "mode": mode,
                    "manualSetPoint": None
                }
            elif mode == "MANUAL":
                # Ensure a manualSetPoint is present for MANUAL mode
                if settings_dict["primary"].get("manualSetPoint") is None:
                    # Use current set_point as a fallback, default to 18.0C (180) if not available
                    current_sp_value = int((self.set_point or 18.0) * 10)
                    settings_dict["primary"]["manualSetPoint"] = {"unit": "C", "value": current_sp_value, "preset": 0} 
                    
                settings_dict["primary"]["mode"] = mode
            else:
                raise ValueError(f"Unsupported mode: {mode}")
            
        # CRITICAL FIX: The presence of manualTimer overrides primary.mode.
        # We must delete it to ensure the mode change (or new manual setpoint) is honored.
        if "manualTimer" in settings_dict:
            del settings_dict["manualTimer"]

        # 3. Serialize the full settings dict back into a tight JSON string
        # This is the string that will be sent inside the outer clientPayload string.
        modified_settings_string = json.dumps(settings_dict, separators=(',', ':'))
        
        # 4. Construct the FULL device object required for clientPayload
        device_data_to_send = {
            # Core identification fields (from parser)
            "handle": self.handle,
            "serialNumber": self.serial_number,
            "name": self.name,
            
            # Full Settings (as a string) - This is the ONLY field that changes
            "settings": modified_settings_string, 
            
            # CRITICAL: Send the FULL current state of these fields (already strings from parsing)
            "measures": self.measures, 
            "schedules": self.schedules,
            
            # CRITICAL: Include all other required top-level fields (from parser)
            "houseHandle": self.house_handle,     # Assuming you store this from parse_device
            "tag": self.tag,                     # Assuming you store this
            "channel": self.channel,               # Assuming you store this
            
            # CRITICAL: Setter-specific fields from captured traffic
            "status": "PENDING",                   # Required status for setter
            "syncVersion": 0,                      # Required value for setter
            "isDeleted": self.is_deleted,          # Assuming you store this
            "role": self.role,                     # Assuming you store this
            "gatewayHandle": self.gateway_handle,  # Assuming you store this
        }
        
        # 5. Call the client's command method to send the active SyncRequest
        # NOTE: The client.py function will now handle the final outer JSON serialization
        await self._client.send_operation(device_data=device_data_to_send)
        
        # 6. Update local state
        # IMPORTANT: We store the string representation for future use
        self.settings = modified_settings_string
        self.mode = mode


    async def set_setpoint(self, value: float):
        """
        Changes the setpoint temperature by forcing the device into MANUAL mode
        and setting the primary manual setpoint.
        """
        if not hasattr(self, "_client") or self._client is None:
            raise Exception("Device client not initialized")

        # 1. Load current settings (string → dict)
        try:
            settings_dict = json.loads(self.settings)
        except (TypeError, json.JSONDecodeError):
            settings_dict = {}
        
        # Calculate target value (Value * 10)
        target_value_int = int(value * 10)

        # 2. Set the device to MANUAL mode and set the value
        if "primary" not in settings_dict:
            settings_dict["primary"] = {}
            
        settings_dict["primary"]["mode"] = "MANUAL"
        settings_dict["primary"]["manualSetPoint"] = {
            "unit": "C",
            "value": target_value_int,
            "preset": 0
        }
        
        # 3. CRUCIAL FIX: Remove the manualTimer to switch to permanent manual mode
        # If the manualTimer field exists, it overrides primary.mode
        if "manualTimer" in settings_dict:
            # We must delete the key entirely to confirm the mode change
            del settings_dict["manualTimer"] 
            
        # 4. Serialize back the modified settings string
        # Use separators=(',', ':') to match the compacted app payload format
        modified_settings_string = json.dumps(settings_dict, separators=(',', ':'))

        # 5. Build the complete device object for clientPayload (Use device's own properties)
        device_data_to_send = {
            "handle": self.handle,
            "serialNumber": self.serial_number,
            "name": self.name,
            "settings": modified_settings_string,
            # Pass through existing values for other key fields
            "measures": self.measures, 
            "schedules": self.schedules,
            "houseHandle": self.house_handle,
            "tag": self.tag,
            "channel": self.channel,
            "status": "PENDING",
            "syncVersion": 0, # syncVersion MUST be 0 for a SETTER request
            "isDeleted": self.is_deleted,
            "role": self.role,
            "gatewayHandle": self.gateway_handle,
        }

        # 6. Send full SyncRequest
        await self._client.send_operation(device_data=device_data_to_send)

        # 7. Update local state
        self.settings = modified_settings_string
        self.set_point = value

class PyFinderBlissAPI:
    def __init__(self, username: str, password: str, max_retries=3, retry_delay=5):
        self._username = username
        self._password = password
        self._client = BlissClientAsync(username, password)
        self._devices = []
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    async def _async_ensure_authenticated(self):
        """
        Internal helper to ensure the client is logged in and the WebSocket is active.
        Re-creates the client and logs in if the existing one is not active.
        NOTE: Assumes BlissClientAsync has a property like `is_logged_in` or `websocket_is_connected`.
        """
        # Assume _client.is_logged_in checks both token and websocket status.
        if hasattr(self._client, "is_logged_in") and self._client.is_logged_in:
            return

        # 1. Try to use the existing client to login/reconnect
        try:
            # We use the private _login assuming it handles initial setup/reconnect
            await self._client._login()
            return
        except Exception:
            # 2. If re-login fails, close and re-create a fresh client instance
            try:
                await self._client.close()
            except Exception:
                pass
            
            self._client = BlissClientAsync(self._username, self._password)
            await self._client._login()

    async def async_setup(self):
        # Use the new robust setup method
        await self._async_ensure_authenticated()

    # --- NEW: Credential Validation (For config_flow.py) ---
    async def async_validate_credentials(self) -> bool:
        """Test the connection and credentials by attempting a login."""
        # Use a fresh client to avoid interference with the main client's state
        temp_client = BlissClientAsync(self._username, self._password)
        try:
            # Attempt the private login method (since that's what async_setup uses)
            await temp_client._login()
            await temp_client.close()
            return True
        except Exception:
            # Catch login failure, connection errors, etc.
            try:
                await temp_client.close()
            except Exception:
                pass
            return False

    async def async_get_devices(self):
        # Ensure connection before starting the fetch loop
        await self._async_ensure_authenticated()

        for attempt in range(self._max_retries):
            try:
                devices_data = await self._client.get_devices()
                self._devices = [BlissDevice(d) for d in devices_data]

                # Attach client reference so setters work
                for dev in self._devices:
                    dev._client = self._client
                    
                return self._devices

            except Exception as e:
                print(f"[FinderBliss] Device fetch failed (attempt {attempt+1}): {e}")
                
                # After a network failure, try to re-authenticate and retry
                if attempt < self._max_retries - 1:
                    await self._async_ensure_authenticated()
                    await asyncio.sleep(self._retry_delay)
                    continue

                # If this was the last attempt, break
                break

        raise Exception("Failed to fetch devices after retries")
    
    # --- Utility Method (NEW) ---
    def _find_device_by_serial(self, serial: str) -> Union['BlissDevice', None]:
        """Internal helper to find a device object by its serial number or name."""
        # Check against serial_number first, fall back to name if serial_number is missing/None
        return next(
            (d for d in self._devices 
             if getattr(d, 'serial_number', getattr(d, 'name')) == serial), 
            None
        )

    # --- NEW: Control Method for Home Assistant Climate Platform ---
    async def async_set_temperature(self, device_serial: str, temperature: float):
        """Set the target setpoint for the device, delegated to the BlissDevice object."""
        # Ensure connection is active before sending the setter command
        await self._async_ensure_authenticated()

        device = self._find_device_by_serial(device_serial)
        if not device:
            raise ValueError(f"Device with serial {device_serial} not found in tracked devices.")
        
        await device.set_setpoint(value=temperature)


    async def async_set_mode(self, device_serial: str, mode: str):
        """Set the operating mode for the device, delegated to the BlissDevice object."""
        # Ensure connection is active before sending the setter command
        await self._async_ensure_authenticated()

        device = self._find_device_by_serial(device_serial)
        if not device:
            raise ValueError(f"Device with serial {device_serial} not found in tracked devices.")
            
        await device.set_mode(mode=mode)

    async def async_close(self):
        await self._client.close()

# Example usage for Home Assistant integration
async def async_main():
    api = PyFinderBlissAPI("123", "123")
    try:
        await api.async_setup()
        devices = await api.async_get_devices()
        for dev in devices:
            print(f"{dev.name}: temp={dev.temperature}, hum={dev.humidity}, setpoint={dev.set_point}, mode={dev.mode}")
    finally:
        await api.async_close()

if __name__ == "__main__":
    asyncio.run(async_main())
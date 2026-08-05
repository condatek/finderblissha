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
        self.set_point = device_data.get("set_point")
        self.manual_set_point = device_data.get("manual_set_point")
        self.mode = device_data.get("mode")
        self.mode_setting = device_data.get("mode_setting")
        self.wifi_level = device_data.get("wifi_level")
        self.battery_level = device_data.get("battery_level")
        self.status = device_data.get("status")
        self.serial_number = device_data.get("serial_number")
        self.model = device_data.get("model")
        self.raw = device_data

        self.role = device_data.get("role")
        self.house_handle = device_data.get("house_handle")
        self.gateway_handle = device_data.get("gateway_handle")
        self.is_deleted = device_data.get("is_deleted")
        self.tag = device_data.get("tag")
        self.channel = device_data.get("channel")

        self.settings = device_data.get("settings", {})
        self.measures = device_data.get("measures", {})
        self.schedules = device_data.get("schedules", [])

        self.season = device_data.get("season")
        self.thermal_differential = device_data.get("thermal_differential")
        self.update_step = device_data.get("update_step")
        self.schedules_parsed = device_data.get("schedules_parsed", [])
        self.automatic_schedule = device_data.get("automatic_schedule", {})
        self.last_update = device_data.get("last_update")
        self.timezone = device_data.get("timezone")
        self.sync_version = device_data.get("sync_version", 0)

    def _build_send_payload(self, modified_settings_string: str) -> dict:
        return {
            "handle": self.handle,
            "serialNumber": self.serial_number,
            "name": self.name,
            "settings": modified_settings_string,
            "measures": self.measures,
            "schedules": self.schedules,
            "houseHandle": self.house_handle,
            "tag": self.tag,
            "channel": self.channel,
            "status": "PENDING",
            "syncVersion": self.sync_version,
            "isDeleted": self.is_deleted,
            "role": self.role,
            "gatewayHandle": self.gateway_handle,
        }

    def _ensure_client(self):
        if not hasattr(self, "_client") or self._client is None:
            raise Exception("Device client not initialized")

    def _load_settings(self) -> dict:
        try:
            return json.loads(self.settings) if isinstance(self.settings, str) else dict(self.settings)
        except (TypeError, json.JSONDecodeError):
            return {}

    def _serialize_settings(self, settings_dict: dict) -> str:
        return json.dumps(settings_dict, separators=(',', ':'))

    async def set_mode(self, mode: str):
        """Change device mode. mode: 'OFF', 'AUTO', 'MANUAL', 'FROST', 'ECO' (uppercase)."""
        mode = mode.upper()
        self._ensure_client()

        settings_dict = self._load_settings()

        if self.tag == "BLISS1":
            if mode == "AUTO":
                settings_dict["mode"] = "AUTO"
                settings_dict.setdefault("manualSchedule", {})["isOn"] = False
            elif mode == "MANUAL":
                # BLISS1 manual = mode stays "AUTO", manualSchedule acts as
                # a timed override (matching the iOS Finder Bliss app behavior).
                settings_dict["mode"] = "AUTO"
                ms = settings_dict.setdefault("manualSchedule", {})
                ms["isOn"] = True
                if ms.get("setPoint") is None:
                    current_sp = self.set_point if isinstance(self.set_point, (int, float)) else 18.0
                    ms["setPoint"] = int(current_sp * 10)
                self._set_manual_timer(ms)
            elif mode in ("OFF", "FROST"):
                settings_dict["mode"] = "OFF"
                settings_dict.setdefault("manualSchedule", {})["isOn"] = False
            else:
                raise ValueError(f"Unsupported BLISS1 mode: {mode}")

        elif self.tag in ("BLISS2", "BLISS-HA"):
            if mode in ["AUTO", "OFF", "FROST", "ECO"]:
                settings_dict["primary"] = {
                    "mode": mode,
                    "manualSetPoint": None
                }
            elif mode == "MANUAL":
                if settings_dict.get("primary", {}).get("manualSetPoint") is None:
                    current_sp = self.set_point if isinstance(self.set_point, (int, float)) else 18.0
                    current_sp_value = int(current_sp * 10)
                    settings_dict.setdefault("primary", {})["manualSetPoint"] = {"unit": "C", "value": current_sp_value, "preset": 0}
                settings_dict.setdefault("primary", {})["mode"] = mode
            else:
                raise ValueError(f"Unsupported mode: {mode}")

            # BLISS2: manualTimer overrides primary.mode, remove it
            if "manualTimer" in settings_dict:
                del settings_dict["manualTimer"]

        modified = self._serialize_settings(settings_dict)
        await self._client.send_operation(device_data=self._build_send_payload(modified))
        self.settings = modified
        self.mode = mode.lower() if mode in ("AUTO", "MANUAL") else "off"

    def _set_manual_timer(self, ms: dict, duration_hours: int = 1) -> None:
        """Set manualSchedule start/stop timestamps in the device's local timezone.

        The thermostat interprets these as local time (no TZ suffix),
        so we must use the device's timezone, not UTC.
        """
        import datetime
        import zoneinfo
        tz = zoneinfo.ZoneInfo(self.timezone) if self.timezone else None
        now = datetime.datetime.now(tz) if tz else datetime.datetime.now()
        ms["start"] = now.strftime("%Y-%m-%dT%H:%M:%S")
        ms["stop"] = (now + datetime.timedelta(hours=duration_hours)).strftime("%Y-%m-%dT%H:%M:%S")

    async def set_setpoint(self, value: float):
        """Set the target temperature, forcing MANUAL mode."""
        self._ensure_client()

        settings_dict = self._load_settings()
        target_value_int = int(value * 10)

        if self.tag == "BLISS1":
            # BLISS1: mode stays "AUTO", manualSchedule is a timed override
            settings_dict["mode"] = "AUTO"
            ms = settings_dict.setdefault("manualSchedule", {})
            ms["isOn"] = True
            ms["setPoint"] = target_value_int
            self._set_manual_timer(ms)
        else:
            # BLISS2 / BLISS-HA
            settings_dict.setdefault("primary", {})["mode"] = "MANUAL"
            settings_dict["primary"]["manualSetPoint"] = {
                "unit": "C",
                "value": target_value_int,
                "preset": 0
            }
            if "manualTimer" in settings_dict:
                del settings_dict["manualTimer"]

        modified = self._serialize_settings(settings_dict)
        await self._client.send_operation(device_data=self._build_send_payload(modified))
        self.settings = modified
        self.set_point = value
        self.mode = "manual"

    async def set_season(self, season: str):
        """Change the season (WINTER/SUMMER) for heating/cooling."""
        season = season.upper()
        if season not in ("WINTER", "SUMMER"):
            raise ValueError(f"Invalid season: {season}")

        self._ensure_client()

        settings_dict = self._load_settings()
        settings_dict["season"] = season

        modified = self._serialize_settings(settings_dict)
        await self._client.send_operation(device_data=self._build_send_payload(modified))
        self.settings = modified
        self.season = season

    async def set_update_step(self, minutes: int):
        """Change the sync/update interval in minutes."""
        self._ensure_client()

        settings_dict = self._load_settings()
        settings_dict["updateStep"] = str(minutes)

        modified = self._serialize_settings(settings_dict)
        await self._client.send_operation(device_data=self._build_send_payload(modified))
        self.settings = modified
        self.update_step = minutes

    async def set_schedule_preset(self, preset_name: str):
        """Apply a named schedule preset to the automaticSchedule."""
        self._ensure_client()

        target_preset = None
        for sched in self.schedules_parsed:
            if sched.get("name") == preset_name:
                target_preset = sched
                break
        if target_preset is None:
            raise ValueError(f"Schedule preset '{preset_name}' not found")

        settings_dict = self._load_settings()
        settings_dict["automaticSchedule"] = {"days": target_preset["days"]}

        modified = self._serialize_settings(settings_dict)
        await self._client.send_operation(device_data=self._build_send_payload(modified))
        self.settings = modified
        self.automatic_schedule = {"days": target_preset["days"]}


class PyFinderBlissAPI:
    def __init__(self, username: str, password: str, max_retries=3, retry_delay=5):
        self._username = username
        self._password = password
        self._client = BlissClientAsync(username, password)
        self._devices = []
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    async def _async_ensure_authenticated(self):
        if hasattr(self._client, "is_logged_in") and self._client.is_logged_in:
            return

        try:
            await self._client._login()
            return
        except Exception:
            try:
                await self._client.close()
            except Exception:
                pass

            self._client = BlissClientAsync(self._username, self._password)
            await self._client._login()

    async def async_setup(self):
        await self._async_ensure_authenticated()

    async def async_validate_credentials(self) -> bool:
        """Test the connection and credentials by attempting a login."""
        temp_client = BlissClientAsync(self._username, self._password)
        try:
            await temp_client._login()
            await temp_client.close()
            return True
        except Exception:
            try:
                await temp_client.close()
            except Exception:
                pass
            return False

    async def async_get_devices(self):
        await self._async_ensure_authenticated()

        for attempt in range(self._max_retries):
            try:
                devices_data = await self._client.get_devices()
                self._devices = [BlissDevice(d) for d in devices_data]

                for dev in self._devices:
                    dev._client = self._client

                return self._devices

            except Exception as e:
                print(f"[FinderBliss] Device fetch failed (attempt {attempt+1}): {e}")

                if attempt < self._max_retries - 1:
                    try:
                        await self._client.reset_connection()
                    except Exception:
                        pass
                    await self._async_ensure_authenticated()
                    await asyncio.sleep(self._retry_delay)
                    continue

                break

        raise Exception("Failed to fetch devices after retries")

    def _find_device_by_serial(self, serial: str) -> Union['BlissDevice', None]:
        return next(
            (d for d in self._devices
             if getattr(d, 'serial_number', getattr(d, 'name')) == serial),
            None
        )

    async def async_set_temperature(self, device_serial: str, temperature: float):
        await self._async_ensure_authenticated()
        device = self._find_device_by_serial(device_serial)
        if not device:
            raise ValueError(f"Device with serial {device_serial} not found in tracked devices.")
        await device.set_setpoint(value=temperature)

    async def async_set_mode(self, device_serial: str, mode: str):
        await self._async_ensure_authenticated()
        device = self._find_device_by_serial(device_serial)
        if not device:
            raise ValueError(f"Device with serial {device_serial} not found in tracked devices.")
        await device.set_mode(mode=mode)

    async def async_set_season(self, device_serial: str, season: str):
        await self._async_ensure_authenticated()
        device = self._find_device_by_serial(device_serial)
        if not device:
            raise ValueError(f"Device with serial {device_serial} not found in tracked devices.")
        await device.set_season(season=season)

    async def async_set_update_step(self, device_serial: str, minutes: int):
        await self._async_ensure_authenticated()
        device = self._find_device_by_serial(device_serial)
        if not device:
            raise ValueError(f"Device with serial {device_serial} not found in tracked devices.")
        await device.set_update_step(minutes=minutes)

    async def async_set_schedule_preset(self, device_serial: str, preset_name: str):
        await self._async_ensure_authenticated()
        device = self._find_device_by_serial(device_serial)
        if not device:
            raise ValueError(f"Device with serial {device_serial} not found in tracked devices.")
        await device.set_schedule_preset(preset_name=preset_name)

    async def async_close(self):
        await self._client.close()


async def async_main():
    api = PyFinderBlissAPI("123", "123")
    try:
        await api.async_setup()
        devices = await api.async_get_devices()
        for dev in devices:
            print(f"{dev.name}: temp={dev.temperature}, hum={dev.humidity}, setpoint={dev.set_point}, mode={dev.mode}, season={dev.season}")
    finally:
        await api.async_close()

if __name__ == "__main__":
    asyncio.run(async_main())

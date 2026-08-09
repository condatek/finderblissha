import asyncio
import json
import logging
import time
from typing import Union
from .client import BlissClientAsync, BlissCommandError
from .device_parser import normalize_schedule_days

_LOGGER = logging.getLogger(__name__)

# A command is re-read from the server before it is reported as applied.
COMMAND_ATTEMPTS = 2
# The ACK means the frame was accepted, not that the new settings are queryable.
COMMAND_VERIFY_DELAY = 1.5
COMMAND_RETRY_DELAY = 3.0
# How long a polled snapshot stays usable as the base for a command payload.
SNAPSHOT_TTL = 15.0

# What each command string should look like once the server has taken it.
_EXPECTED_MODE = {
    "OFF": "off",
    "FROST": "off",
    "AUTO": "auto",
    "MANUAL": "manual",
    "ECO": "eco",
}


def commanded_mode(device: 'BlissDevice') -> str | None:
    """The mode the server has been told to hold.

    Not the same question as `device.mode` on a BLISS2, where the mode is read
    from `measures` - the thermostat's own echo, which only moves when it next
    checks in, minutes later. Verifying a write against that would time out on
    every command, so read the commanded setting instead. BLISS1 already
    derives `mode` from `settings`, which is the commanded side.
    """
    if getattr(device, "tag", None) == "BLISS1":
        return getattr(device, "mode", None)
    setting = str(getattr(device, "mode_setting", "") or "").lower()
    if not setting or setting == "n/a":
        return None
    return "off" if setting == "frost" else setting


def _set_point_matches(reported, expected) -> bool:
    """Compare set points that round-trip through tenths of a degree."""
    try:
        return abs(float(reported) - float(expected)) < 0.05
    except (TypeError, ValueError):
        return False


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
        # One command at a time per account: each one re-reads the snapshot it
        # builds its payload from, and two commands interleaving would hand the
        # second a snapshot the first has already superseded.
        self._command_lock = asyncio.Lock()
        self._snapshot_ts = 0.0
        self._snapshot_dirty = True

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
                devices = [BlissDevice(d) for d in devices_data]

                for dev in devices:
                    dev._client = self._client

                devices, partial = self._merge_known_devices(devices)
                self._devices = devices
                self._snapshot_ts = time.monotonic()
                # Anything carried over still holds an older poll's syncVersion,
                # so this snapshot must not be the base for the next command.
                self._snapshot_dirty = partial
                return self._devices

            except Exception as e:
                _LOGGER.warning("Device fetch failed (attempt %s): %s", attempt + 1, e)

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

    @staticmethod
    def _device_key(device: 'BlissDevice'):
        return getattr(device, "serial_number", None) or getattr(device, "name", None)

    def _merge_known_devices(self, devices: list) -> tuple[list, bool]:
        """Carry over devices the server left out of a partial payload.

        A SyncRequest normally answers with the whole inventory, but the server
        also pushes deltas naming only the device a command just touched, and
        one of those arriving out of turn is indistinguishable from a full
        answer here. Taken at face value the other thermostats look deleted:
        their entities drop to unknown, and a command aimed at one of them
        fails with "not found in tracked devices".
        """
        known = {self._device_key(d): d for d in self._devices}
        if not known:
            return devices, False

        seen = {self._device_key(d) for d in devices}
        missing = [device for key, device in known.items() if key not in seen]
        if not missing:
            return devices, False

        _LOGGER.warning(
            "Partial device payload: %s of %s devices returned, carrying over %s",
            len(devices), len(known),
            ", ".join(str(getattr(d, "name", "?")) for d in missing),
        )
        return devices + missing, True

    def _find_device_by_serial(self, serial: str, devices=None) -> Union['BlissDevice', None]:
        return next(
            (d for d in (self._devices if devices is None else devices)
             if getattr(d, 'serial_number', getattr(d, 'name')) == serial),
            None
        )

    async def _async_fresh_devices(self):
        """Return a snapshot recent enough to build a command payload from.

        Every payload carries the device's own syncVersion from whichever poll
        produced it. Sending one built on a superseded snapshot risks the
        server discarding it as a conflict, which is indistinguishable from
        success at this layer - so any successful write invalidates the
        snapshot for the next command.
        """
        if self._snapshot_dirty or (time.monotonic() - self._snapshot_ts) > SNAPSHOT_TTL:
            return await self.async_get_devices()
        return self._devices

    async def _async_run_command(self, device_serial: str, apply_fn, verify_fn, description: str):
        """Apply a command and confirm the server took it, retrying if it did not.

        An ACK only proves the frame was accepted; whether the settings landed
        is a separate question. A lost write is otherwise invisible - the next
        poll just reports the old value, which downstream reads as somebody
        having changed it by hand. Returns the snapshot that confirmed it, so
        the caller can publish state it has actually verified.
        """
        async with self._command_lock:
            last_error: Exception | None = None

            for attempt in range(1, COMMAND_ATTEMPTS + 1):
                await self._async_ensure_authenticated()
                devices = await self._async_fresh_devices()
                device = self._find_device_by_serial(device_serial, devices)
                if device is None:
                    raise ValueError(f"Device with serial {device_serial} not found in tracked devices.")

                try:
                    await apply_fn(device)
                except ValueError:
                    # A bad argument will not become valid on a retry.
                    raise
                except Exception as err:
                    last_error = err
                    _LOGGER.warning(
                        "%s failed on attempt %s/%s: %s",
                        description, attempt, COMMAND_ATTEMPTS, err,
                    )
                else:
                    self._snapshot_dirty = True
                    await asyncio.sleep(COMMAND_VERIFY_DELAY)
                    devices = await self.async_get_devices()
                    confirmed = self._find_device_by_serial(device_serial, devices)
                    if confirmed is not None and verify_fn(confirmed):
                        return devices

                    last_error = BlissCommandError(
                        f"{description}: the server did not apply the command"
                    )
                    _LOGGER.warning(
                        "%s was not confirmed on attempt %s/%s",
                        description, attempt, COMMAND_ATTEMPTS,
                    )

                if attempt < COMMAND_ATTEMPTS:
                    await asyncio.sleep(COMMAND_RETRY_DELAY)

            raise last_error

    async def async_set_temperature(self, device_serial: str, temperature: float):
        return await self._async_run_command(
            device_serial,
            lambda device: device.set_setpoint(value=temperature),
            lambda device: _set_point_matches(device.manual_set_point, temperature),
            f"Set point {temperature}",
        )

    async def async_set_mode(self, device_serial: str, mode: str):
        expected = _EXPECTED_MODE.get(mode.upper())
        return await self._async_run_command(
            device_serial,
            lambda device: device.set_mode(mode=mode),
            lambda device: commanded_mode(device) == expected,
            f"Mode {mode.upper()}",
        )

    async def async_set_season(self, device_serial: str, season: str):
        expected = season.upper()
        return await self._async_run_command(
            device_serial,
            lambda device: device.set_season(season=season),
            lambda device: str(device.season or "").upper() == expected,
            f"Season {expected}",
        )

    async def async_set_update_step(self, device_serial: str, minutes: int):
        return await self._async_run_command(
            device_serial,
            lambda device: device.set_update_step(minutes=minutes),
            lambda device: device.update_step == minutes,
            f"Sync interval {minutes}",
        )

    async def async_set_schedule_preset(self, device_serial: str, preset_name: str):
        def _applied(device: 'BlissDevice') -> bool:
            target = next(
                (s for s in device.schedules_parsed if s.get("name") == preset_name),
                None,
            )
            if target is None:
                return False
            active = normalize_schedule_days(device.automatic_schedule.get("days", []))
            return active == normalize_schedule_days(target.get("days", []))

        return await self._async_run_command(
            device_serial,
            lambda device: device.set_schedule_preset(preset_name=preset_name),
            _applied,
            f"Schedule preset {preset_name!r}",
        )

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

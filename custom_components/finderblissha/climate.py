"""Climate platform for Finder Bliss (BLISS1 / BLISS2) thermostats."""

from __future__ import annotations

import asyncio
import logging
import time
import zoneinfo
from datetime import datetime
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .pyfinderbliss.device_parser import normalize_schedule_days
from .pyfinderbliss.pyfinderbliss_wrapper import BlissDevice, PyFinderBlissAPI

_LOGGER = logging.getLogger(__name__)

# Ceiling on how long a commanded value stays visible without confirmation.
# Commands confirm and clear it themselves; this only bounds the damage if the
# task running one is cancelled before it can.
OPTIMISTIC_TIMEOUT = 90


def _scheduled_set_point(days: list, tz_name: str | None) -> float | None:
    """Return the set point the schedule calls for right now, in C.

    Day numbering is 1=Monday..7=Sunday, matching isoweekday(). The active
    block is the last set point at or before now; before the first block of
    the day it carries over from the most recent earlier day, wrapping the
    week.
    """
    if not days:
        return None

    by_day: dict[int, list] = {}
    for day_entry in days:
        day_num = day_entry.get("day")
        if day_num is None:
            continue
        by_day[day_num] = sorted(
            day_entry.get("setPoints", []),
            key=lambda sp: (sp.get("hour", 0), sp.get("minute", 0))
        )
    if not by_day:
        return None

    try:
        tz = zoneinfo.ZoneInfo(tz_name) if tz_name else None
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        tz = None
    now = datetime.now(tz)

    day = now.isoweekday()
    minutes_now = now.hour * 60 + now.minute
    for offset in range(7):
        set_points = by_day.get(day, [])
        if offset == 0:
            set_points = [
                sp for sp in set_points
                if sp.get("hour", 0) * 60 + sp.get("minute", 0) <= minutes_now
            ]
        if set_points:
            value = set_points[-1].get("setPoint")
            if isinstance(value, (int, float)):
                return value / 10
        day = day - 1 or 7

    return None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the climate platform from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DataUpdateCoordinator = entry_data["coordinator"]
    api: PyFinderBlissAPI = entry_data["api"]

    entities = []
    for device in coordinator.data:
        if not isinstance(device, BlissDevice):
            continue
        if getattr(device, "temperature", None) not in (None, "N/A"):
            entities.append(FinderBlissClimate(coordinator, api, device))

    async_add_entities(entities, True)


class FinderBlissClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a Finder Bliss Thermostat.

    HVAC mode mapping:
      - HEAT = winter season (schedule or manual)
      - COOL = summer season (schedule or manual)
      - AUTO = resume schedule (transitions back to HEAT/COOL after refresh)
      - OFF  = frost protection

    The AUTO mode acts as a momentary trigger: selecting it sends the device
    back to schedule mode, then the next coordinator refresh resolves it to
    HEAT or COOL based on the active season. In Apple Home the mode briefly
    shows "Auto" then settles to "Heat" or "Cool".

    Presets select the active schedule program.
    """

    _attr_has_entity_name = True
    _attr_name = "Thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
    _attr_min_temp = 5.0
    _attr_max_temp = 35.0
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: DataUpdateCoordinator, api: PyFinderBlissAPI, device: BlissDevice):
        super().__init__(coordinator)
        self._api = api
        self._device_serial = getattr(device, "serial_number", getattr(device, "name", None))
        self._attr_unique_id = f"finderbliss_climate_{self._device_serial}"
        self._command_lock = asyncio.Lock()
        # Device attribute -> (commanded value, expiry). See _device_value.
        self._optimistic: dict[str, tuple[Any, float]] = {}

    @property
    def supported_features(self) -> ClimateEntityFeature:
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        dev = self._find_device()
        if dev:
            schedules = getattr(dev, "schedules_parsed", [])
            if any(s.get("name") for s in schedules):
                features |= ClimateEntityFeature.PRESET_MODE
        return features

    def _find_device(self) -> BlissDevice | None:
        for d in self.coordinator.data:
            if getattr(d, "serial_number", getattr(d, "name", None)) == self._device_serial:
                return d
        return None

    def _device_value(self, name: str, default: Any = None) -> Any:
        """Read a device attribute, preferring a command still in flight.

        Every coordinator refresh rebuilds the BlissDevice objects from
        scratch, so a value written onto them optimistically is gone at the
        next poll. Held on the entity instead, the commanded value stays put
        until the command confirms or fails - so a slow write never surfaces
        as a state change looking like somebody turned the zone back on.
        """
        pending = self._optimistic.get(name)
        if pending is not None:
            value, expires = pending
            if time.monotonic() < expires:
                return value
            del self._optimistic[name]

        dev = self._find_device()
        if dev is None:
            return default
        value = getattr(dev, name, default)
        return default if value is None else value

    def _set_optimistic(self, values: dict[str, Any] | None) -> None:
        if not values:
            return
        expires = time.monotonic() + OPTIMISTIC_TIMEOUT
        for key, value in values.items():
            self._optimistic[key] = (value, expires)
        self.async_write_ha_state()

    def _clear_optimistic(self, values: dict[str, Any] | None) -> None:
        for key in values or {}:
            self._optimistic.pop(key, None)

    def _get_season(self) -> str:
        return self._device_value("season", "WINTER")

    # --- Properties ---

    @property
    def current_temperature(self) -> float | None:
        dev = self._find_device()
        temp = getattr(dev, "temperature", None)
        return float(temp) if temp not in (None, "N/A") else None

    @property
    def target_temperature(self) -> float | None:
        dev = self._find_device()
        if dev is None:
            return None
        if self.hvac_mode == HVACMode.OFF:
            # Match Finder mobile app logic while OFF:
            # winter -> 5 C, summer -> 35 C.
            return self._attr_max_temp if self._get_season() == "SUMMER" else self._attr_min_temp

        # In schedule mode the device-reported set point lags: it is what the
        # thermostat last uploaded, so it keeps showing the frost point for a
        # few sync cycles after leaving OFF, and every schedule step lands late.
        # Resolve the schedule locally instead, as the mobile app does.
        if str(self._device_value("mode", "")).lower() == "auto":
            scheduled = _scheduled_set_point(
                self._device_value("automatic_schedule", {}).get("days", []),
                getattr(dev, "timezone", None),
            )
            if scheduled is not None:
                return scheduled

        set_point_raw = self._device_value("set_point")
        if set_point_raw is None or str(set_point_raw).upper() == "N/A":
            return None
        try:
            return float(set_point_raw)
        except (ValueError, TypeError):
            return None

    @property
    def hvac_mode(self) -> HVACMode:
        mode = self._device_value("mode")
        if mode is None or str(mode).lower() == "off":
            return HVACMode.OFF
        # Both "auto" and "manual" resolve to HEAT/COOL based on season
        season = self._get_season()
        return HVACMode.COOL if season == "SUMMER" else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        dev = self._find_device()
        if dev is None:
            return None
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        relay_status = getattr(dev, "status", "OFF")
        season = self._get_season()
        if relay_status == "ON":
            return HVACAction.COOLING if season == "SUMMER" else HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_modes(self) -> list[str] | None:
        dev = self._find_device()
        if dev is None:
            return None
        schedules = getattr(dev, "schedules_parsed", [])
        names = [s.get("name") for s in schedules if s.get("name")]
        return names if names else None

    @property
    def preset_mode(self) -> str | None:
        dev = self._find_device()
        if dev is None:
            return None
        if str(self._device_value("mode", "")).lower() != "auto":
            return None

        schedules = getattr(dev, "schedules_parsed", [])
        current_auto = self._device_value("automatic_schedule", {})
        if schedules and current_auto:
            current_days = normalize_schedule_days(current_auto.get("days", []))
            for sched in schedules:
                preset_days = normalize_schedule_days(sched.get("days", []))
                if current_days == preset_days:
                    return sched.get("name")
        return None

    @property
    def device_info(self) -> DeviceInfo:
        dev = self._find_device()
        serial = getattr(dev, "serial_number", self._device_serial) if dev else self._device_serial
        return DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=getattr(dev, "name", self._device_serial) if dev else self._device_serial,
            manufacturer="Finder",
            model=getattr(dev, "model", None) if dev else None,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dev = self._find_device()
        if not dev:
            return {}
        return {
            "season": self._device_value("season"),
            "operating_mode": self._device_value("mode"),
        }

    # --- Control Methods ---

    async def _async_execute_api_command(self, api_coroutine, *args, optimistic=None, **kwargs) -> None:
        """Execute an API command, serialized against other commands on this entity."""
        async with self._command_lock:
            await self._async_command(api_coroutine, *args, optimistic=optimistic, **kwargs)

    async def _async_command(self, api_coroutine, *args, optimistic=None, **kwargs) -> None:
        """Run one command with the entity lock already held.

        The commanded value goes up straight away so Apple Home reacts at once,
        but it is the API layer that decides whether the command counts: it
        returns only once the server has been read back and agrees. That
        verified snapshot is pushed into the coordinator instead of waiting up
        to a poll interval for the same news.

        On failure the commanded value is dropped and the error raised. A
        command the server silently declined must not read as applied - that is
        what makes a lost write show up minutes later as a phantom manual
        change.
        """
        self._set_optimistic(optimistic)
        try:
            devices = await api_coroutine(*args, **kwargs)
        except Exception as err:
            self._clear_optimistic(optimistic)
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"Finder Bliss command failed for {self._device_serial}: {err}"
            ) from err

        self._clear_optimistic(optimistic)
        if devices:
            self.coordinator.async_set_updated_data(devices)
        else:
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode.

        OFF   → frost protection
        AUTO  → resume schedule, then resolves to HEAT/COOL on next refresh
        HEAT  → set season to winter + manual mode
        COOL  → set season to summer + manual mode
        """
        if hvac_mode == HVACMode.OFF:
            await self._async_execute_api_command(
                self._api.async_set_mode, self._device_serial, "OFF",
                optimistic={"mode": "off"},
            )
            return

        if hvac_mode == HVACMode.AUTO:
            # Resume schedule — after refresh, hvac_mode resolves to HEAT/COOL
            await self._async_execute_api_command(
                self._api.async_set_mode, self._device_serial, "AUTO",
                optimistic={"mode": "auto"},
            )
            return

        # HEAT or COOL → set season (if needed) + manual mode.
        # Both commands run inside one lock acquisition so a second command on
        # this entity cannot land between them.
        season = "SUMMER" if hvac_mode == HVACMode.COOL else "WINTER"

        async with self._command_lock:
            if self._get_season() != season:
                await self._async_command(
                    self._api.async_set_season, self._device_serial, season,
                    optimistic={"season": season},
                )
            await self._async_command(
                self._api.async_set_mode, self._device_serial, "MANUAL",
                optimistic={"mode": "manual"},
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        target_temp = kwargs.get(ATTR_TEMPERATURE)
        if target_temp is None:
            return

        # Setting temperature from OFF turns the thermostat on in manual
        if self.hvac_mode == HVACMode.OFF:
            season = self._get_season()
            target_hvac = HVACMode.COOL if season == "SUMMER" else HVACMode.HEAT
            await self.async_set_hvac_mode(target_hvac)

        await self._async_execute_api_command(
            self._api.async_set_temperature, self._device_serial, target_temp,
            optimistic={"set_point": target_temp, "mode": "manual"},
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Apply a named schedule and switch to auto mode."""
        dev = self._find_device()
        schedule = next(
            (s for s in getattr(dev, "schedules_parsed", []) if s.get("name") == preset_mode),
            None,
        ) if dev else None

        await self._async_execute_api_command(
            self._api.async_set_schedule_preset, self._device_serial, preset_mode,
            optimistic={"automatic_schedule": {"days": schedule["days"]}} if schedule else None,
        )
        await self._async_execute_api_command(
            self._api.async_set_mode, self._device_serial, "AUTO",
            optimistic={"mode": "auto"},
        )

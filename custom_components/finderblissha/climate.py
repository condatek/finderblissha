"""Climate platform for Finder Bliss (BLISS1 / BLISS2) thermostats."""

from __future__ import annotations

import asyncio
import logging
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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .pyfinderbliss.pyfinderbliss_wrapper import BlissDevice, PyFinderBlissAPI

_LOGGER = logging.getLogger(__name__)


def _normalize_schedule_days(days: list) -> list:
    """Normalize schedule days for reliable comparison."""
    normalized = []
    for day_entry in sorted(days, key=lambda d: d.get("day", 0)):
        set_points = sorted(
            day_entry.get("setPoints", []),
            key=lambda sp: (sp.get("hour", 0), sp.get("minute", 0))
        )
        normalized.append({
            "day": day_entry.get("day"),
            "setPoints": [
                {"hour": sp.get("hour"), "minute": sp.get("minute"), "setPoint": sp.get("setPoint")}
                for sp in set_points
            ]
        })
    return normalized


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

    def _get_season(self) -> str:
        dev = self._find_device()
        return getattr(dev, "season", "WINTER") if dev else "WINTER"

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
        set_point_raw = getattr(dev, "set_point", None)
        if set_point_raw is None or str(set_point_raw).upper() == "N/A":
            return None
        try:
            return float(set_point_raw)
        except (ValueError, TypeError):
            return None

    @property
    def hvac_mode(self) -> HVACMode:
        dev = self._find_device()
        if dev is None:
            return HVACMode.OFF
        mode = getattr(dev, "mode", "off")
        if mode == "off":
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
        mode = getattr(dev, "mode", "off")
        if mode != "auto":
            return None

        schedules = getattr(dev, "schedules_parsed", [])
        current_auto = getattr(dev, "automatic_schedule", {})
        if schedules and current_auto:
            current_days = _normalize_schedule_days(current_auto.get("days", []))
            for sched in schedules:
                preset_days = _normalize_schedule_days(sched.get("days", []))
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
            "season": getattr(dev, "season", None),
            "operating_mode": getattr(dev, "mode", None),
        }

    # --- Control Methods ---

    async def _async_execute_api_command(self, api_coroutine, *args, **kwargs) -> None:
        """Execute an API command and update HA state optimistically.

        Serialized with a lock so concurrent commands from Apple Home
        (e.g. HVAC mode + temperature at the same time) don't race.

        The wrapper methods (set_mode, set_setpoint, etc.) update the
        BlissDevice attributes in-place.  These are the same objects in
        coordinator.data, so the entity properties immediately reflect
        the new values.  We push that state to HA right away instead of
        triggering a coordinator refresh, which would send a SyncRequest
        over the same WebSocket and risk reading stale buffered messages.
        The regular polling interval syncs the full state from the server.
        """
        async with self._command_lock:
            await api_coroutine(*args, **kwargs)
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
                self._api.async_set_mode, self._device_serial, "OFF"
            )
            return

        if hvac_mode == HVACMode.AUTO:
            # Resume schedule — after refresh, hvac_mode resolves to HEAT/COOL
            await self._async_execute_api_command(
                self._api.async_set_mode, self._device_serial, "AUTO"
            )
            return

        # HEAT or COOL → set season (if needed) + manual mode
        # Both commands run inside one lock acquisition so no intermediate
        # coordinator refresh can replace the device objects between them.
        dev = self._find_device()
        current_season = getattr(dev, "season", "WINTER") if dev else "WINTER"

        async with self._command_lock:
            if hvac_mode == HVACMode.COOL and current_season != "SUMMER":
                await self._api.async_set_season(self._device_serial, "SUMMER")
            elif hvac_mode == HVACMode.HEAT and current_season != "WINTER":
                await self._api.async_set_season(self._device_serial, "WINTER")

            await self._api.async_set_mode(self._device_serial, "MANUAL")
        self.async_write_ha_state()

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
            self._api.async_set_temperature, self._device_serial, target_temp
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Apply a named schedule and switch to auto mode."""
        await self._async_execute_api_command(
            self._api.async_set_schedule_preset, self._device_serial, preset_mode
        )
        await self._async_execute_api_command(
            self._api.async_set_mode, self._device_serial, "AUTO"
        )

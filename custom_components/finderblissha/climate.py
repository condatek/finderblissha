"""Climate platform for Finder Bliss (BLISS1 / BLISS2) thermostats."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
)
from homeassistant.config_entries import ConfigEntry 

from .const import DOMAIN
from .pyfinderbliss.pyfinderbliss_wrapper import PyFinderBlissAPI, BlissDevice

_LOGGER = logging.getLogger(__name__)

# --- Mode Mapping ---
HA_TO_BLISS_MODE = {
    HVACMode.HEAT: "MANUAL",
    HVACMode.AUTO: "AUTO",
    HVACMode.OFF: "OFF",
}

BLISS_TO_HA_MODE = {v: k for k, v in HA_TO_BLISS_MODE.items()}

SUPPORTED_HA_MODES = list(HA_TO_BLISS_MODE.keys())


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the climate platform from a config entry."""
    
    entry_data = hass.data[DOMAIN][entry.entry_id]

    coordinator: DataUpdateCoordinator = entry_data["coordinator"]
    api: PyFinderBlissAPI = entry_data["api"]

    entities = []
    # Coordinator.data holds the list of BlissDevice objects after the API call
    for device in coordinator.data:
        if not isinstance(device, BlissDevice):
            continue
        
        # Only add a climate entity if the device reports a set point
        if getattr(device, "set_point", None) is not None:
            _LOGGER.debug(f"Adding climate entity for device: {device.name}")
            entities.append(FinderBlissClimate(coordinator, api, device))

    async_add_entities(entities, True)


class FinderBlissClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a Finder Bliss Thermostat."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = SUPPORTED_HA_MODES
    
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE 
        | ClimateEntityFeature.TURN_OFF 
        | ClimateEntityFeature.TURN_ON
    )

    _attr_min_temp = 5.0
    _attr_max_temp = 35.0
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: DataUpdateCoordinator, api: PyFinderBlissAPI, device: BlissDevice):
        """Initialize the climate entity."""
        super().__init__(coordinator)
        self._api = api
        
        self._device_serial = getattr(device, "serial_number", getattr(device, "name", None))
        
        self._attr_unique_id = f"finderbliss_climate_{self._device_serial}"

    def _find_device(self) -> BlissDevice | None:
        """Find the device in the coordinator data."""
        for d in self.coordinator.data:
            if getattr(d, "serial_number", getattr(d, "name", None)) == self._device_serial:
                return d
        return None

    # --- Properties ---
    
    @property
    def name(self) -> str:
        """Return the name of the climate device."""
        dev = self._find_device()
        base_name = getattr(dev, "name", self._device_serial)
        return f"{base_name} Climate"

    @property
    def current_temperature(self) -> float | None:
        """Return the current ambient temperature."""
        dev = self._find_device()
        temp = getattr(dev, "temperature", None)
        return float(temp) if temp not in (None, "N/A") else None

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we are trying to reach (manual_set_point if valid, else set_point)."""
        if self.hvac_mode == HVACMode.OFF:
            return None

        dev = self._find_device()
        if dev is None:
            return None

        manual_sp = getattr(dev, "manual_set_point", None)
        # Use manual_set_point only if > 0
        if manual_sp is not None and isinstance(manual_sp, (int, float)) and manual_sp > 0:
            return float(manual_sp)

        set_point = getattr(dev, "set_point", None)

        _LOGGER.debug(
            "FinderBlissClimate[%s]: hvac_mode=%s | mode_setting=%s | set_point=%s | manual_set_point=%s | temperature=%s",
            self._device_serial,
            self.hvac_mode,
            getattr(self._find_device(), 'mode_setting', None),
            getattr(self._find_device(), 'set_point', None),
            getattr(self._find_device(), 'manual_set_point', None),
            getattr(self._find_device(), 'temperature', None),
)


        return float(set_point) if set_point not in (None, "N/A") else None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current operation mode (e.g., HEAT, AUTO, OFF)."""
        dev = self._find_device()
        mode = getattr(dev, "mode", None)
        
        return BLISS_TO_HA_MODE.get(str(mode).upper(), HVACMode.OFF)

    @property
    def device_info(self):
        """Return device information for device registry linking."""
        dev = self._find_device()
        serial = getattr(dev, "serial_number", self._device_serial) if dev else self._device_serial
        return {
            "identifiers": {(DOMAIN, serial)},
            "name": getattr(dev, "name", self._device_serial) if dev else self._device_serial,
            "manufacturer": "Finder",
            "model": getattr(dev, "model", None) if dev else None,
            "via_device": (DOMAIN, "gateway") 
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device specific attributes."""
        dev = self._find_device()
        if not dev:
            return {}

        attrs: dict[str, Any] = {}
        
        attrs["raw_mode"] = getattr(dev, "mode", None)
        attrs["raw_mode_setting"] = getattr(dev, "mode_setting", None)
        
        # Add the raw data attributes to the device for diagnostics/viewing
        attrs.update(dev.raw)
        
        return attrs

    # --- Control Methods (STABILITY FIXES APPLIED HERE) ---

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        
        bliss_mode = HA_TO_BLISS_MODE.get(hvac_mode)
        
        if bliss_mode is None:
            _LOGGER.error("Unsupported HVAC mode: %s", hvac_mode)
            return

        try:
            await self._api.async_set_mode(self._device_serial, bliss_mode)
            
        except Exception as err:
            _LOGGER.error("Failed to set HVAC mode to %s for device %s: %s", 
                          bliss_mode, self._device_serial, err)
            raise

        # Request immediate refresh to update state
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature (set_point)."""

        target_temp = kwargs.get(ATTR_TEMPERATURE)
        if target_temp is None:
            return

        # 1. First, ensure the device is in MANUAL/HEAT mode to accept a setpoint change
        if self.hvac_mode != HVACMode.HEAT:
            await self.async_set_hvac_mode(HVACMode.HEAT)

        try:
            await self._api.async_set_temperature(self._device_serial, target_temp)
            
        except Exception as err:
            _LOGGER.error("Failed to set temperature to %s for device %s: %s", 
                          target_temp, self._device_serial, err)
            raise

        # Request immediate refresh to update state
        await self.coordinator.async_request_refresh()
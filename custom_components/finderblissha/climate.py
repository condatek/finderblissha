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
        """Return the temperature we are trying to reach (set_point)."""
        
        dev = self._find_device()
        if dev is None:
            return None

        # 1. CRITICAL: Check the HVAC mode *first*. If we are OFF, target temp must be None.
        # This prevents the UI from trying to default to current_temperature.
        if self.hvac_mode == HVACMode.OFF:
            return None

        # 2. Get the set_point value directly from the device object.
        # Ensure we always get a string/float value.
        set_point_raw = getattr(dev, "set_point", None) 
            
        # 3. Handle cases where the data might be missing or an invalid string
        if set_point_raw is None or str(set_point_raw).upper() == "N/A":
            # If the setpoint is genuinely unavailable, return None.
            return None
        
        try:
            # 4. Return the value, explicitly cast to float.
            return float(set_point_raw)
        except (ValueError, TypeError):
            # Log an error if we cannot cast the value, but return None to avoid a crash.
            _LOGGER.error("Bliss set_point value '%s' is not a valid number.", set_point_raw)
            return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current operation mode (e.g., HEAT, AUTO, OFF)."""
        dev = self._find_device()
        mode = getattr(dev, "mode_setting", None)
        
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

    async def _async_execute_api_command(self, api_coroutine, *args, **kwargs) -> None:
        """
        Executes a PyFinderBliss API command, ensuring the coordinator/connection
        is refreshed as a first line of defense against WebSocket errors.
        """
        
        # HACK/FIX: Force an initial coordinator refresh to ensure the WebSocket 
        # is connected before attempting a control command.
        await self.coordinator.async_request_refresh()
        
        try:
            # Execute the actual API command
            await api_coroutine(*args, **kwargs)
            
        except RuntimeError as err:
            # Re-raise any critical errors that aren't addressed by the refresh logic
            if "WebSocket not connected" in str(err):
                _LOGGER.error("Bliss API failed to connect/execute control command after refresh: %s", err)
            raise 

        # Final refresh to update HA state with the result from the thermostat
        await self.coordinator.async_request_refresh()


    # --- Control Methods (Using the new command executor) ---

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        
        bliss_mode = HA_TO_BLISS_MODE.get(hvac_mode)
        
        if bliss_mode is None:
            _LOGGER.error("Unsupported HVAC mode: %s", hvac_mode)
            return

        try:
            await self._async_execute_api_command(
                self._api.async_set_mode, 
                self._device_serial, 
                bliss_mode
            )
            
        except Exception as err:
            _LOGGER.error("Failed to set HVAC mode to %s for device %s: %s", 
                          bliss_mode, self._device_serial, err)
            # Re-raise if the error wasn't handled by the wrapper
            raise


    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature (set_point)."""

        target_temp = kwargs.get(ATTR_TEMPERATURE)
        if target_temp is None:
            return

        # 1. First, ensure the device is in MANUAL/HEAT mode to accept a setpoint change
        if self.hvac_mode != HVACMode.HEAT:
            # NOTE: async_set_hvac_mode already uses the command executor and handles refresh
            await self.async_set_hvac_mode(HVACMode.HEAT)

        try:
            await self._async_execute_api_command(
                self._api.async_set_temperature, 
                self._device_serial, 
                target_temp
            )
            
        except Exception as err:
            _LOGGER.error("Failed to set temperature to %s for device %s: %s", 
                          target_temp, self._device_serial, err)
            # Re-raise if the error wasn't handled by the wrapper
            raise
"""Sensor platform for Finder Bliss (BLISS1 / BLISS2)."""

from __future__ import annotations
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
)

from .const import DOMAIN
from .pyfinderbliss.pyfinderbliss_wrapper import BlissDevice

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the sensor platform from a config entry."""
    
    # FIX: Recupera i dati utilizzando la struttura per entry.entry_id
    try:
        entry_data = hass.data[DOMAIN][entry.entry_id]
    except KeyError:
        _LOGGER.error("Configuration entry data not found for sensor platform. Check __init__.py storage.")
        return

    coordinator: DataUpdateCoordinator = entry_data.get("coordinator")
    
    if not coordinator:
        # Questa riga non dovrebbe più essere raggiunta se l'accesso a entry_data va a buon fine,
        # ma la manteniamo per sicurezza.
        _LOGGER.error("Coordinator not found for sensor platform")
        return

    # coordinator already refreshed in __init__.py
    
    entities = build_entities_from_devices(coordinator)
    async_add_entities(entities, True)


# -------------------------
# Entity builder
# -------------------------
def build_entities_from_devices(coordinator: DataUpdateCoordinator):
    entities = []
    for device in coordinator.data:
        if not isinstance(device, BlissDevice):
            continue
        _LOGGER.debug(f"Processing device: {device.name}")

        if device.temperature not in (None, "N/A"):
            entities.append(FinderBlissTemperatureSensor(coordinator, device))
        if device.humidity not in (None, "N/A"):
            entities.append(FinderBlissHumiditySensor(coordinator, device))
        if device.battery_level not in (None, "N/A"):
            entities.append(FinderBlissBatterySensor(coordinator, device))
        if getattr(device, "wifi_level", None) not in (None, "N/A"):
            entities.append(FinderBlissWifiSensor(coordinator, device))
        if getattr(device, "mode", None) is not None:
            entities.append(FinderBlissModeSensor(coordinator, device))
        if getattr(device, "manual_set_point", None) not in (None, "N/A"):
            entities.append(FinderBlissManualSetPointSensor(coordinator, device))
        if getattr(device, "set_point", None) not in (None, "N/A"):
            entities.append(FinderBlissSetPointSensor(coordinator, device))
    return entities


# -------------------------
# Base sensor
# -------------------------
class FinderBlissBaseSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator: DataUpdateCoordinator, device: BlissDevice, key: str, friendly: str, unit: str | None, attr: str):
        super().__init__(coordinator)
        self._device_serial = getattr(device, "serial_number", getattr(device, "name", None))
        self._key = key
        self._friendly = friendly
        self._unit = unit
        self._attr = attr
        self._unique_id = f"finderbliss_{self._device_serial}_{key}"

    def _find_device(self):
        for d in self.coordinator.data:
            if getattr(d, "serial_number", getattr(d, "name", None)) == self._device_serial:
                return d
        return None

    @property
    def name(self) -> str:
        dev = self._find_device()
        base_name = getattr(dev, "name", self._device_serial)
        return f"{base_name} {self._friendly}"

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def native_value(self):
        dev = self._find_device()
        if not dev:
            return None
        val = getattr(dev, self._attr, None)
        return None if val == "N/A" else val

    @property
    def native_unit_of_measurement(self):
        return self._unit

    @property
    def device_info(self):
        dev = self._find_device()
        serial = getattr(dev, "serial_number", self._device_serial) if dev else self._device_serial
        return {
            "identifiers": {(DOMAIN, serial)},
            "name": getattr(dev, "name", self._device_serial) if dev else self._device_serial,
            "manufacturer": "Finder",
            "model": getattr(dev, "model", None) if dev else None,
        }

    @property
    def extra_state_attributes(self):
        dev = self._find_device()
        attrs = {"status": getattr(dev, "status", None)}
        raw = getattr(dev, "raw", None)
        if raw:
            attrs["raw"] = raw
        return attrs


# -------------------------
# Specific sensors
# -------------------------
class FinderBlissTemperatureSensor(FinderBlissBaseSensor):
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "temperature", "Temperature", UnitOfTemperature.CELSIUS, "temperature")


class FinderBlissHumiditySensor(FinderBlissBaseSensor):
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "humidity", "Humidity", PERCENTAGE, "humidity")


class FinderBlissBatterySensor(FinderBlissBaseSensor):
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "battery", "Battery", PERCENTAGE, "battery_level")


class FinderBlissWifiSensor(FinderBlissBaseSensor):
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "wifi", "WiFi Level", "dBm", "wifi_level")


class FinderBlissModeSensor(FinderBlissBaseSensor):
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "mode", "Mode", None, "mode")


class FinderBlissManualSetPointSensor(FinderBlissBaseSensor):
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "manual_set_point", "Manual Set Point", UnitOfTemperature.CELSIUS, "manual_set_point")


class FinderBlissSetPointSensor(FinderBlissBaseSensor):
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "set_point", "Set Point", UnitOfTemperature.CELSIUS, "set_point")


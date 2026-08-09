"""Select platform for Finder Bliss — sync interval profile."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .pyfinderbliss.pyfinderbliss_wrapper import BlissDevice, PyFinderBlissAPI

_LOGGER = logging.getLogger(__name__)

UPDATE_PROFILES: dict[str, int] = {
    "Energy saving": 1,
    "Normal": 2,
    "Fast": 3,
    "Super fast": 4,
}

LEVEL_TO_PROFILE: dict[int, str] = {v: k for k, v in UPDATE_PROFILES.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DataUpdateCoordinator = entry_data["coordinator"]
    api: PyFinderBlissAPI = entry_data["api"]

    entities = []
    for device in coordinator.data:
        if not isinstance(device, BlissDevice):
            continue
        if getattr(device, "update_step", None) is not None:
            entities.append(FinderBlissUpdateProfileSelect(coordinator, api, device))

    async_add_entities(entities, True)


class FinderBlissUpdateProfileSelect(CoordinatorEntity, SelectEntity):
    """Sync interval profile for a Finder Bliss thermostat."""

    _attr_has_entity_name = True
    _attr_name = "Sync profile"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(UPDATE_PROFILES.keys())

    def __init__(self, coordinator: DataUpdateCoordinator, api: PyFinderBlissAPI, device: BlissDevice):
        super().__init__(coordinator)
        self._api = api
        self._device_serial = getattr(device, "serial_number", getattr(device, "name", None))
        self._attr_unique_id = f"finderbliss_{self._device_serial}_update_profile"

    def _find_device(self) -> BlissDevice | None:
        for d in self.coordinator.data:
            if getattr(d, "serial_number", getattr(d, "name", None)) == self._device_serial:
                return d
        return None

    @property
    def current_option(self) -> str | None:
        dev = self._find_device()
        if not dev:
            return None
        level = getattr(dev, "update_step", None)
        if level is None:
            return None
        return LEVEL_TO_PROFILE.get(level, "Normal")

    @property
    def extra_state_attributes(self) -> dict:
        dev = self._find_device()
        level = getattr(dev, "update_step", None) if dev else None
        return {"sync_level": level}

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

    async def async_select_option(self, option: str) -> None:
        level = UPDATE_PROFILES.get(option)
        if level is None:
            _LOGGER.error("Unknown sync profile: %s", option)
            return
        try:
            devices = await self._api.async_set_update_step(self._device_serial, level)
        except Exception as err:
            raise HomeAssistantError(
                f"Finder Bliss command failed for {self._device_serial}: {err}"
            ) from err
        # The API returns the snapshot that confirmed the change.
        self.coordinator.async_set_updated_data(devices)

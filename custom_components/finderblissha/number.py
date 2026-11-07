"""Per-thermostat settings for Finder Bliss."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .pyfinderbliss.pyfinderbliss_wrapper import BlissDevice


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        Bliss1OverrideDuration(data["coordinator"], data["api"], device)
        for device in data["coordinator"].data
        if isinstance(device, BlissDevice) and device.tag == "BLISS1"
    ])


class Bliss1OverrideDuration(CoordinatorEntity, RestoreNumber):
    """Duration used for future manual commands; 0 means indefinite."""

    _attr_has_entity_name = True
    _attr_translation_key = "override_duration"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 168
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, api, device):
        super().__init__(coordinator)
        self._api = api
        self._serial = device.serial_number or device.name
        self._name = device.name
        self._model = device.model
        self._attr_unique_id = f"finderbliss_{self._serial}_override_duration"
        self._attr_native_value = api.bliss1_override_hours(self._serial)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            value = last.native_value
            if 0 <= value <= 168 and float(value).is_integer():
                self._attr_native_value = int(value)
        self._api.set_bliss1_override_hours(self._serial, int(self._attr_native_value))

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, self._serial)}, name=self._name,
                          manufacturer="Finder", model=self._model)

    @property
    def extra_state_attributes(self):
        device = next((d for d in self.coordinator.data or []
                       if (d.serial_number or d.name) == self._serial), None)
        kind, duration = active_override(device)
        return {"active_override": kind, "active_duration_hours": duration}

    async def async_set_native_value(self, value: float) -> None:
        if not 0 <= value <= 168 or not float(value).is_integer():
            raise ValueError("Override duration must be a whole number from 0 to 168")
        self._api.set_bliss1_override_hours(self._serial, int(value))
        self._attr_native_value = int(value)
        self.async_write_ha_state()


def active_override(device):
    """Read the active override, not the preference for future commands."""
    if device is None:
        return "unknown", None
    settings = device._load_settings()
    mode = settings.get("mode")
    schedule = settings.get("manualSchedule") or {}
    if mode == "MANUAL":
        return "indefinite", 0
    if mode == "AUTO" and schedule.get("isOn"):
        try:
            duration = (datetime.fromisoformat(schedule["stop"]) -
                        datetime.fromisoformat(schedule["start"])).total_seconds() / 3600
        except (KeyError, TypeError, ValueError):
            duration = None
        return "timed", duration
    return "none", None

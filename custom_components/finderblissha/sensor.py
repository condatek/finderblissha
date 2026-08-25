"""Sensor platform for Finder Bliss (BLISS1 / BLISS2)."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .pyfinderbliss.device_parser import normalize_schedule_days, parse_set_point
from .pyfinderbliss.pyfinderbliss_wrapper import BlissDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensor platform from a config entry."""
    try:
        entry_data = hass.data[DOMAIN][entry.entry_id]
    except KeyError:
        _LOGGER.error("Configuration entry data not found for sensor platform")
        return

    coordinator: DataUpdateCoordinator = entry_data.get("coordinator")
    if not coordinator:
        _LOGGER.error("Coordinator not found for sensor platform")
        return

    entities = build_entities_from_devices(coordinator)
    async_add_entities(entities, True)


def build_entities_from_devices(coordinator: DataUpdateCoordinator):
    entities = []
    for device in coordinator.data:
        if not isinstance(device, BlissDevice):
            continue
        _LOGGER.debug("Processing device: %s", device.name)

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
        if getattr(device, "season", None) is not None:
            entities.append(FinderBlissSeasonSensor(coordinator, device))
        if getattr(device, "thermal_differential", None) is not None:
            entities.append(FinderBlissThermalDifferentialSensor(coordinator, device))
        if getattr(device, "automatic_schedule", None):
            entities.append(FinderBlissScheduleSensor(coordinator, device))
        if getattr(device, "last_update", None) is not None:
            entities.append(FinderBlissLastUpdateSensor(coordinator, device))
    return entities


class FinderBlissBaseSensor(CoordinatorEntity, SensorEntity):
    """Base sensor for Finder Bliss entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        device: BlissDevice,
        key: str,
        attr: str,
    ):
        super().__init__(coordinator)
        self._device_serial = getattr(device, "serial_number", getattr(device, "name", None))
        self._attr = attr
        self._attr_unique_id = f"finderbliss_{self._device_serial}_{key}"

    def _find_device(self) -> BlissDevice | None:
        for d in self.coordinator.data:
            if getattr(d, "serial_number", getattr(d, "name", None)) == self._device_serial:
                return d
        return None

    @property
    def native_value(self):
        dev = self._find_device()
        if not dev:
            return None
        val = getattr(dev, self._attr, None)
        return None if val == "N/A" else val

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


class FinderBlissTemperatureSensor(FinderBlissBaseSensor):
    _attr_name = "Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "temperature", "temperature")


class FinderBlissHumiditySensor(FinderBlissBaseSensor):
    _attr_name = "Humidity"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "humidity", "humidity")


class FinderBlissBatterySensor(FinderBlissBaseSensor):
    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "battery", "battery_level")


class FinderBlissWifiSensor(FinderBlissBaseSensor):
    _attr_name = "WiFi level"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "wifi", "wifi_level")


class FinderBlissModeSensor(FinderBlissBaseSensor):
    _attr_name = "Mode"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "mode", "mode")


class FinderBlissManualSetPointSensor(FinderBlissBaseSensor):
    _attr_name = "Manual set point"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "manual_set_point", "manual_set_point")


class FinderBlissSetPointSensor(FinderBlissBaseSensor):
    _attr_name = "Set point"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "set_point", "set_point")


class FinderBlissSeasonSensor(FinderBlissBaseSensor):
    _attr_name = "Season"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "season", "season")


class FinderBlissThermalDifferentialSensor(FinderBlissBaseSensor):
    _attr_name = "Thermal differential"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "thermal_differential", "thermal_differential")


class FinderBlissLastUpdateSensor(FinderBlissBaseSensor):
    _attr_name = "Last sync"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "last_update", "last_update")

    @property
    def native_value(self):
        dev = self._find_device()
        if not dev:
            return None
        raw = getattr(dev, "last_update", None)
        if not raw:
            return None
        from datetime import datetime
        try:
            tz_name = getattr(dev, "timezone", None)
            import zoneinfo
            tz = zoneinfo.ZoneInfo(tz_name) if tz_name else None
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None and tz:
                dt = dt.replace(tzinfo=tz)
            return dt
        except (ValueError, KeyError):
            return None


DAY_NAMES = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}


def _format_schedule(auto_schedule: dict, schedules_parsed: list) -> tuple[str | None, dict]:
    """Build a human-readable schedule summary."""
    days = auto_schedule.get("days", [])
    if not days:
        return None, {}

    active_preset = None
    current_norm = normalize_schedule_days(days)
    for sched in schedules_parsed:
        if normalize_schedule_days(sched.get("days", [])) == current_norm:
            active_preset = sched.get("name")
            break

    schedule_attrs = {}
    for day_entry in sorted(days, key=lambda d: d.get("day", 0)):
        day_num = day_entry.get("day", 0)
        day_name = DAY_NAMES.get(day_num, f"Day {day_num}")
        set_points = sorted(
            day_entry.get("setPoints", []),
            key=lambda sp: (sp.get("hour", 0), sp.get("minute", 0))
        )

        blocks = []
        for i, sp in enumerate(set_points):
            hour = sp.get("hour", 0)
            minute = sp.get("minute", 0)
            temp = parse_set_point(sp.get("setPoint"))

            start = f"{hour:02d}:{minute:02d}"
            if i + 1 < len(set_points):
                next_sp = set_points[i + 1]
                end = f"{next_sp.get('hour', 0):02d}:{next_sp.get('minute', 0):02d}"
            else:
                end = "24:00"
            blocks.append(f"{start}-{end}: {temp}°C")

        schedule_attrs[day_name] = blocks

    return active_preset, schedule_attrs


class FinderBlissScheduleSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing the active schedule with per-day time blocks."""

    _attr_has_entity_name = True
    _attr_name = "Schedule"

    def __init__(self, coordinator: DataUpdateCoordinator, device: BlissDevice):
        super().__init__(coordinator)
        self._device_serial = getattr(device, "serial_number", getattr(device, "name", None))
        self._attr_unique_id = f"finderbliss_{self._device_serial}_schedule"

    def _find_device(self) -> BlissDevice | None:
        for d in self.coordinator.data:
            if getattr(d, "serial_number", getattr(d, "name", None)) == self._device_serial:
                return d
        return None

    @property
    def native_value(self) -> str | None:
        dev = self._find_device()
        if not dev:
            return None
        auto_schedule = getattr(dev, "automatic_schedule", {})
        schedules_parsed = getattr(dev, "schedules_parsed", [])
        preset_name, _ = _format_schedule(auto_schedule, schedules_parsed)
        return preset_name or "Custom"

    @property
    def extra_state_attributes(self) -> dict:
        dev = self._find_device()
        if not dev:
            return {}
        auto_schedule = getattr(dev, "automatic_schedule", {})
        schedules_parsed = getattr(dev, "schedules_parsed", [])
        _, schedule_attrs = _format_schedule(auto_schedule, schedules_parsed)
        attrs = dict(schedule_attrs)
        preset_names = [s.get("name") for s in schedules_parsed if s.get("name")]
        if preset_names:
            attrs["available_presets"] = preset_names
        return attrs

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

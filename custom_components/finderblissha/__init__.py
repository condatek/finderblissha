"""The Finder Bliss Thermostats integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, PLATFORMS, DEFAULT_SCAN_INTERVAL
from .pyfinderbliss.pyfinderbliss_wrapper import PyFinderBlissAPI

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Finder Bliss from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    api = PyFinderBlissAPI(entry.data["username"], entry.data["password"])
    try:
        await api.async_setup()
    except Exception as err:
        err_msg = str(err).lower()
        if "invalid" in err_msg or "unauthorized" in err_msg or "401" in err_msg:
            raise ConfigEntryAuthFailed("Invalid credentials") from err
        raise ConfigEntryNotReady(f"Cannot connect: {err}") from err

    async def async_update_data():
        try:
            return await api.async_get_devices()
        except Exception as err:
            err_msg = str(err).lower()
            if "invalid" in err_msg or "unauthorized" in err_msg or "401" in err_msg:
                raise ConfigEntryAuthFailed("Invalid credentials") from err
            raise

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="finderbliss_coordinator",
        update_method=async_update_data,
        update_interval=SCAN_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        api: PyFinderBlissAPI = entry_data["api"]
        await api.async_close()

        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow deleting a device from the UI only if it is no longer on the account.

    Thermostats still reported by the API are managed by the integration and
    must not be removed by hand (they would just reappear). A device whose
    serial is no longer returned (e.g. a thermostat replaced or renamed
    upstream, leaving a stale entry behind) can be deleted.
    """
    known_serials: set[str] = set()
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if entry_data and (coordinator := entry_data.get("coordinator")) and coordinator.data:
        for device in coordinator.data:
            serial = getattr(device, "serial_number", None) or getattr(device, "name", None)
            if serial is not None:
                known_serials.add(str(serial))

    # Removable when none of this device's identifiers map to a live thermostat.
    return not any(
        str(identifier[1]) in known_serials
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN
    )

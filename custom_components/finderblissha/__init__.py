from datetime import timedelta
import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.config_entries import ConfigEntry # Import necessario per il tipaggio

from .const import DOMAIN, PLATFORMS, DEFAULT_SCAN_INTERVAL
from .pyfinderbliss.pyfinderbliss_wrapper import PyFinderBlissAPI

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Finder Bliss from a config entry."""
    # Assicura che esista il dizionario principale per il DOMAIN
    hass.data.setdefault(DOMAIN, {})
    
    # 1. Setup API
    # Usiamo entry.data per le credenziali (memorizzate nella configurazione)
    api = PyFinderBlissAPI(entry.data["username"], entry.data["password"])
    # NOTA: Assicurati che entry.data contenga "username" e "password"
    await api.async_setup()
    
    # 2. Setup Coordinator
    async def async_update_data():
        """Fetch data from API."""
        return await api.async_get_devices()

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="finderbliss_coordinator",
        update_method=async_update_data,
        update_interval=SCAN_INTERVAL,
    )
    
    # Esegue il primo aggiornamento per popolare coordinator.data
    await coordinator.async_config_entry_first_refresh()

    # 3. Memorizza API e Coordinator in hass.data[DOMAIN][entry.entry_id]
    # QUESTA È LA MODIFICA CHIAVE che risolve il KeyError in climate.py
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    # 4. Inoltra la configurazione a tutte le piattaforme (sensor, climate, ecc.)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    
    # 1. Scarica le piattaforme (climate, sensor, ecc.)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        # 2. Rimuove i dati specifici di questa configurazione
        hass.data[DOMAIN].pop(entry.entry_id)
        
        # 3. Pulisce la chiave principale DOMAIN se non ci sono altre configurazioni
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
            
    return unload_ok
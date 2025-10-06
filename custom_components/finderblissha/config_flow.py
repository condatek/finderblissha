# finderblissha/config_flow.py
"""Config flow for Finder Bliss Home Assistant integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

# Import the necessary constants and the API wrapper
from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD
from .pyfinderbliss.pyfinderbliss_wrapper import PyFinderBlissAPI

_LOGGER = logging.getLogger(__name__)

# Schema for the initial user input form
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    """Validate the user input allows us to connect.

    Data contains the user input credentials.
    Returns info dict on success, raises an exception otherwise.
    """
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]

    # Initialize the API wrapper for validation
    api = PyFinderBlissAPI(username, password)
    
    try:
        # This calls the method we added earlier to pyfinderbliss_wrapper.py
        if not await api.async_validate_credentials():
             # If validation returns False (e.g., login failed), raise invalid_auth
             raise InvalidAuth
    except HomeAssistantError as err:
        # Re-raise HA errors
        raise err
    except Exception as err:
        # Catch connection errors or other unexpected API failures
        _LOGGER.exception("Validation failed during setup: %s", err)
        raise CannotConnect from err

    # If successful, return the title to be used for the config entry
    return {"title": username}


class FinderBlissConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Finder Bliss."""

    VERSION = 1
    # Allow only one instance of the integration
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL 

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # 1. Set unique ID to prevent duplicates
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()

            # 2. Validate credentials
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception: # Catch any uncaught errors
                _LOGGER.exception("Unexpected exception during setup.")
                errors["base"] = "unknown"
            else:
                # Success! Create the config entry.
                return self.async_create_entry(title=info["title"], data=user_input)

        # Show the form again if input is missing or validation failed
        return self.async_show_form(
            step_id="user", 
            data_schema=STEP_USER_DATA_SCHEMA, 
            errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate invalid username/password."""
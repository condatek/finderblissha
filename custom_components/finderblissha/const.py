"""Constants for Finder Bliss Home Assistant integration."""

DOMAIN = "finderblissha"

DEFAULT_SCAN_INTERVAL = 60  # seconds

CONF_USERNAME = "username"
CONF_PASSWORD = "password"

PLATFORMS = ["sensor", "climate", "select", "number"]

# Zero selects indefinite manual mode; positive values are hours.
CONF_BLISS1_OVERRIDE_HOURS = "bliss1_override_hours"
DEFAULT_BLISS1_OVERRIDE_HOURS = 1

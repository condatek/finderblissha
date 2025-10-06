import json

def parse_device_data(payload):
    """Parse the full serverPayload JSON into a list of device dicts."""
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
        devices = data.get("devices", [])
        return [parse_device(device) for device in devices if device.get("tag") in ["BLISS1", "BLISS2"]]
    except json.JSONDecodeError:
        return []


# ----------------- MODE HANDLING -----------------
def determine_bliss1_mode(settings: dict) -> str:
    """Determine operating mode for BLISS1 devices."""
    is_on = settings.get("manualSchedule", {}).get("isOn", False)
    mode = settings.get("mode", "OFF").upper()

    if mode == "AUTO":
        return "auto"
    elif mode == "OFF" and is_on:
        return "manual"
    elif mode == "OFF" and not is_on:
        return "off"
    return "unknown"


def determine_bliss2_mode(measures: dict) -> str:
    """Determine operating mode for BLISS2 devices."""
    mode = measures.get("mode", 0)
    # Aggiungo mode 2 che corrisponde a OFF/ECO/FROST
    return {
        0: "OFF", 
        1: "AUTO", 
        2: "OFF",  # <-- ASSUNZIONE: Mode 2 è la modalità "SPENTO" (ECO/FROST non attivo)
        3: "MANUAL"
    }.get(mode, "UNKNOWN")



# ----------------- MAIN DEVICE PARSER -----------------
def parse_device(device: dict) -> dict:
    """
    Parse a single BLISS device entry into normalized dict.
    Crucially, captures raw JSON strings and all metadata needed for setter operations.
    """
    
    # 1. Capture ALL MANDATORY SETTER FIELDS & RAW DATA
    handle = device.get("handle")
    tag = device.get("tag")
    name = device.get("name", "Unknown")
    serial_number = device.get("serialNumber", "Unknown")
    model = device.get("tag", "Unknown") # Model is typically the tag
    role = device.get("role")                          # CRITICAL for setter
    house_handle = device.get("houseHandle")           # CRITICAL for setter
    gateway_handle = device.get("gatewayHandle")       # CRITICAL for setter
    is_deleted = device.get("isDeleted", False)        # CRITICAL for setter

    # CRITICAL: Capture the raw JSON strings for resending in setter operations
    settings_raw = device.get("settings", "{}")
    measures_raw = device.get("measures", "{}")
    schedules_raw = device.get("schedules", "[]")

    # 2. PARSE STRINGS for internal attribute calculation
    measures_parsed = safe_json_load(measures_raw)
    settings_parsed = safe_json_load(settings_raw)

    # Determine mode depending on model
    mode = determine_bliss2_mode(measures_parsed) if tag == "BLISS2" else determine_bliss1_mode(settings_parsed)

    # Base attributes
    status = measures_parsed.get("status", "N/A")
    humidity = parse_value(measures_parsed.get("humidity"))
    wifi_level = measures_parsed.get("wifiLevel", "N/A")
    battery_level = parse_value(measures_parsed.get("batteryLevel"))

    # Temperature
    temperature_value = parse_temperature(measures_parsed.get("temperature"))

    # Standard set point (the one thermostat is using)
    set_point = parse_set_point(measures_parsed.get("setPoint"))

    # Manual set point (user override value)
    if tag == "BLISS2":
        primary_settings = settings_parsed.get("primary", {})
        mode_setting = primary_settings.get("mode", "N/A")
        manual_set_point_value = parse_set_point(primary_settings.get("manualSetPoint"))
    else:  # BLISS1
        mode_setting = settings_parsed.get("mode", "N/A")
        manual_set_point_value = parse_set_point(settings_parsed.get("manualSchedule", {}).get("setPoint"))

    # 3. RETURN the dictionary, prioritizing RAW strings for setter compatibility
    return {
        "name": name,
        "handle": handle,
        "serial_number": serial_number,
        "model": model,
        "mode": mode,
        "status": status,
        "temperature": temperature_value,
        "humidity": humidity,
        "set_point": set_point,
        "manual_set_point": manual_set_point_value,
        "mode_setting": mode_setting,
        "wifi_level": wifi_level,
        "battery_level": battery_level,
        
        # CRITICAL SETTER METADATA (snake_case keys)
        "role": device.get("role"),
        "house_handle": device.get("houseHandle"),
        "gateway_handle": device.get("gatewayHandle"),
        "is_deleted": device.get("isDeleted", False),
        "tag": device.get("tag"),                         # Ensure 'tag' is returned
        "channel": device.get("channel"),                 # Ensure 'channel' is returned if present
        
        # CRITICAL RAW JSON STRINGS (for setter payload)
        "settings": settings_raw,   # Full raw JSON string
        "measures": measures_raw,   # Full raw JSON string
        "schedules": schedules_raw, # Full raw JSON string
    }


# ----------------- HELPERS -----------------
def safe_json_load(data):
    """Safely loads JSON strings into dict, returns {} on failure."""
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return {}
    elif isinstance(data, dict):
        return data
    return {}


def parse_temperature(temp_data):
    """Parse and normalize temperature (tenths of °C → °C)."""
    if isinstance(temp_data, dict):
        value = temp_data.get("value")
    else:
        value = temp_data

    if isinstance(value, (int, float)):
        return value / 10
    return "N/A"


def parse_set_point(set_point_data):
    """Parse and normalize set point values (tenths of °C → °C)."""
    if isinstance(set_point_data, dict):
        value = set_point_data.get("value")
    else:
        value = set_point_data

    if isinstance(value, (int, float)):
        return value / 10
    return "N/A"


def parse_value(value):
    """Generic safe parser for numeric values (e.g., humidity %, battery %)."""
    if isinstance(value, dict):
        value = value.get("value")

    if isinstance(value, (int, float)):
        return value
    return "N/A"

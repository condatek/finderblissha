import json

MODEL_DISPLAY_NAMES = {
    "BLISS1": "Bliss WiFi Next (1C.91)",
    "BLISS2": "Bliss 2",
}


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
    """Determine operating mode for BLISS1 devices.

    BLISS1 manual mode = mode:"AUTO" + manualSchedule.isOn:true
    (a timed override on top of the schedule).
    mode:"OFF" = frost protection / off.
    mode:"AUTO" + isOn:false = schedule (auto).
    """
    is_on = settings.get("manualSchedule", {}).get("isOn", False)
    mode = settings.get("mode", "OFF").upper()

    if mode == "OFF":
        return "off"
    if mode == "AUTO" and is_on:
        return "manual"
    if mode == "AUTO":
        return "auto"
    return "unknown"


def determine_bliss2_mode(measures: dict) -> str:
    """Determine operating mode for BLISS2 devices.

    Lower case to match determine_bliss1_mode: consumers compare against
    "off"/"auto"/"manual", and the setters write the same lower-case values
    back onto the device, so a BLISS2 reporting "OFF" here never matched and
    flipped case on every command.
    """
    mode = measures.get("mode", 0)
    return {
        0: "off",
        1: "auto",
        2: "off",
        3: "manual"
    }.get(mode, "unknown")


def normalize_schedule_days(days: list) -> list:
    """Normalize schedule days for reliable comparison."""
    normalized = []
    for day_entry in sorted(days or [], key=lambda d: d.get("day", 0)):
        set_points = sorted(
            day_entry.get("setPoints", []),
            key=lambda sp: (sp.get("hour", 0), sp.get("minute", 0))
        )
        normalized.append({
            "day": day_entry.get("day"),
            "setPoints": [
                {"hour": sp.get("hour"), "minute": sp.get("minute"), "setPoint": sp.get("setPoint")}
                for sp in set_points
            ]
        })
    return normalized



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
    model = MODEL_DISPLAY_NAMES.get(tag, tag)
    role = device.get("role")
    house_handle = device.get("houseHandle")
    gateway_handle = device.get("gatewayHandle")
    is_deleted = device.get("isDeleted", False)
    last_update = device.get("lastUpdate")
    timezone = device.get("tz")
    sync_version = device.get("syncVersion", 0)

    # CRITICAL: Capture the raw JSON strings for resending in setter operations
    settings_raw = device.get("settings", "{}")
    measures_raw = device.get("measures", "{}")
    schedules_raw = device.get("schedules", "[]")

    # 2. PARSE STRINGS for internal attribute calculation
    measures_parsed = safe_json_load(measures_raw)
    settings_parsed = safe_json_load(settings_raw)

    # Determine mode depending on tag
    mode = determine_bliss2_mode(measures_parsed) if tag == "BLISS2" else determine_bliss1_mode(settings_parsed)

    # Base attributes
    status = measures_parsed.get("status", "N/A")
    humidity = parse_value(measures_parsed.get("humidity"))
    wifi_level = measures_parsed.get("wifiLevel", "N/A")
    battery_level = parse_battery_level(measures_parsed.get("batteryLevel"))

    # Temperature
    temperature_value = parse_temperature(measures_parsed.get("temperature"))

    # Active set point
    # In manual mode, read from settings (updated immediately after setter).
    # In auto mode, read from measures (reported by the thermostat hardware).
    if tag == "BLISS1":
        if mode == "manual":
            set_point = parse_set_point(
                settings_parsed.get("manualSchedule", {}).get("setPoint")
            )
        else:
            set_point = parse_set_point(measures_parsed.get("loggerSetPoint"))
    else:
        if mode == "manual":
            set_point = parse_set_point(
                settings_parsed.get("primary", {}).get("manualSetPoint")
            )
        else:
            set_point = parse_set_point(measures_parsed.get("setPoint"))

    # Season (WINTER / SUMMER)
    season = settings_parsed.get("season")

    # Thermal differential (hysteresis) — stored in tenths of °C
    thermal_differential_raw = settings_parsed.get("thermalDifferential")
    thermal_differential = thermal_differential_raw / 10 if isinstance(thermal_differential_raw, (int, float)) else None

    # Update interval (sync frequency in minutes)
    update_step_raw = settings_parsed.get("updateStep")
    update_step = int(update_step_raw) if update_step_raw is not None else None

    # Automatic schedule (the currently active schedule program)
    automatic_schedule = settings_parsed.get("automaticSchedule", {})

    # Named schedule presets (parsed from the schedules JSON array)
    schedules_parsed = safe_json_load_list(schedules_raw)

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
        "season": season,
        "thermal_differential": thermal_differential,
        "update_step": update_step,
        "automatic_schedule": automatic_schedule,
        "schedules_parsed": schedules_parsed,
        "last_update": last_update,
        "timezone": timezone,

        # CRITICAL SETTER METADATA (snake_case keys)
        "role": device.get("role"),
        "house_handle": device.get("houseHandle"),
        "gateway_handle": device.get("gatewayHandle"),
        "is_deleted": device.get("isDeleted", False),
        "tag": device.get("tag"),
        "channel": device.get("channel"),
        "sync_version": sync_version,

        # CRITICAL RAW JSON STRINGS (for setter payload)
        "settings": settings_raw,
        "measures": measures_raw,
        "schedules": schedules_raw,
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


def safe_json_load_list(data):
    """Safely loads JSON strings into list, returns [] on failure."""
    if isinstance(data, str):
        try:
            result = json.loads(data)
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            return []
    elif isinstance(data, list):
        return data
    return []


def parse_temperature(temp_data):
    """Parse and normalize temperature (tenths of C to C)."""
    if isinstance(temp_data, dict):
        value = temp_data.get("value")
    else:
        value = temp_data

    if isinstance(value, (int, float)):
        return value / 10
    return "N/A"


def parse_set_point(set_point_data):
    """Parse and normalize set point values (tenths of C to C)."""
    if isinstance(set_point_data, dict):
        value = set_point_data.get("value")
    else:
        value = set_point_data

    if isinstance(value, (int, float)):
        return value / 10
    return "N/A"


def parse_battery_level(raw):
    """Convert raw battery voltage (tenths of volts) to percentage.

    4xAA (2S2P): ~3.0V fresh, ~2.1V cutoff.
    Calibrated against the Finder Bliss iOS app's 3-dot display:
      1 dot  = below ~2.55V
      2 dots = ~2.55V to ~2.85V
      3 dots = above ~2.85V
    """
    if isinstance(raw, dict):
        raw = raw.get("value")
    if not isinstance(raw, (int, float)):
        return "N/A"
    VOLTAGE_MAX = 30  # 3.0V (fresh 2S2P alkaline)
    VOLTAGE_MIN = 21  # 2.1V (cutoff)
    pct = (raw - VOLTAGE_MIN) / (VOLTAGE_MAX - VOLTAGE_MIN) * 100
    return max(0, min(100, round(pct)))


def parse_value(value):
    """Generic safe parser for numeric values (e.g., humidity %, battery %)."""
    if isinstance(value, dict):
        value = value.get("value")

    if isinstance(value, (int, float)):
        return value
    return "N/A"

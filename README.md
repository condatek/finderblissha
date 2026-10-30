## Disclaimer
  
This project is not affiliated, associated, authorized, endorsed by, or in any way officially connected with Finder S.p.A.  
The Finder BLISS name, as well as related names, marks, emblems and images, are registered trademarks of their respective owners.  
This integration is provided for **research and interoperability purposes only**.  
Use it at your own risk.  
  
# Finder Bliss Thermostats (Home Assistant Custom Component)
  
A Home Assistant custom integration for **Finder BLISS** thermostats using the unofficial `pyFinderBliss` API client.  
  
### Supported devices  
  
| Model | Tag | Tested |  
|---|---|---|  
| Bliss WiFi Next (1C.91) | BLISS1 | Yes |  
| Bliss 2 | BLISS2 | Partial |  
  
---  
  
## Features  
  
### Climate entity  
  
- **Current & target temperature** monitoring and control  
- **HVAC modes**: Off (frost protection), Heat, Cool, Auto  
- **Heating / Cooling** — switching between Heat and Cool automatically changes the device season (Winter/Summer)  
- **HVAC action** — shows Heating, Cooling, or Idle based on the relay status  
- **Schedule presets** — select named schedule programs configured in the Finder Bliss app (e.g. "Estate", "Freddo PT")  
  
### Sensors  
  
| Sensor | Device class | Unit | Category |  
|---|---|---|---|  
| Temperature | `temperature` | °C | — |  
| Humidity | `humidity` | % | — |  
| Battery | `battery` | % | Diagnostic |  
| WiFi level | `signal_strength` | dBm | Diagnostic |  
| Mode | — | — | Diagnostic |  
| Set point | `temperature` | °C | — |  
| Manual set point | `temperature` | °C | — |  
| Season | — | — | Diagnostic |  
| Thermal differential | `temperature` | °C | Diagnostic |  
| Schedule | — | — | — |  
| Last sync | `timestamp` | — | Diagnostic |
  
The **Schedule** sensor shows the active preset name as its state and exposes per-day time blocks as attributes (e.g. `Monday: ["06:00-20:00: 19.0°C", "20:00-24:00: 18.0°C"]`).  
  
Battery percentage is calibrated for 4xAA batteries in a 2S2P configuration (2.1V–3.0V range).  
  
### Sync profile (select entity)  
  
An editable select entity to control the device's cloud sync interval:  
  
| Profile | Interval |  
|---|---|  
| Energy saving | 30 min |  
| Normal | 15 min |  
| Fast | 5 min |  
| Super fast | 1 min |  
  
Categorized as a **Config** entity.  
  
### Credential management  
  
- **Reconfigure** — update username/password from the integration's settings page (three-dot menu)  
- **Reauth** — if credentials become invalid, Home Assistant automatically prompts for new ones  
  
---  
  
## Installation (via HACS - Recommended)  
  
This integration can be installed easily using the Home Assistant Community Store (HACS).  
  
1. Open **HACS** in your Home Assistant UI.  
2. Go to **Integrations** section.  
3. Click the **three dots** in the top right corner and select **Custom repositories**.  
4. Enter the URL of this repository: `https://github.com/condatek/finderblissha`  
5. Select the **Category** as `Integration`.  
6. Click **ADD**.  
7. HACS will list the new repository. Search for **"Finder Bliss"** and click **Download**.  
8. **Restart Home Assistant** to ensure the new component is loaded.  
  
## Configuration  
  
After restarting Home Assistant:  
  
1. Go to **Settings > Devices & Services > Integrations**.  
2. Click **ADD INTEGRATION**.  
3. Search for **"Finder Bliss Thermostats"**.  
4. Enter your Finder Bliss app credentials (email and password).  
5. The integration validates the credentials and creates climate, sensor, and select entities for each thermostat.  
  
To update credentials later, go to the integration entry, click the three-dot menu, and select **Reconfigure**.  
  
## Manual Installation (Not Recommended)  
  
1. Download the contents of this repository.  
2. Copy the entire `finderblissha` folder into your Home Assistant's `custom_components` directory (e.g. `/config/custom_components/finderblissha/`).  
3. Restart Home Assistant.  
4. Follow the configuration steps above.  
  
---  
  
## Notes  
  
- The integration communicates via the Finder Bliss cloud API (OAuth2 + SignalR WebSocket). It does **not** use local/Bluetooth communication.  
- **Off mode** on BLISS1 devices activates frost protection (anti-freeze), not a full power-off.  
- Thermal differential (hysteresis) is exposed as a read-only diagnostic sensor. It can be configured from the Finder Bliss app.  
- The API is unofficial and may break if Finder changes their cloud service.  

---

## Changelog

### v0.5.0

This version brings substantial improvements and new features, largely thanks to contributions from @marl1w.

*   **Full BLISS1 Support:** Comprehensive support for BLISS1 devices, including accurate manual mode behavior (timed override) and mode detection aligning with the official Finder Bliss app.
*   **Enhanced Climate Control:**
    *   Adds **HVAC Modes** (Off, Heat, Cool, Auto) and **HVAC Action** (Heating, Cooling, Idle).
    *   **Season Control:** Automatic switching between Winter/Summer seasons when changing between Heat/Cool modes.
    *   **Schedule Presets:** Select named schedule programs via `climate.preset_mode`.
    *   Fixed set point reading logic for manual and auto modes.
*   **New Sensor Entities:** Introduces sensors for **Season**, **Thermal Differential**, **Schedule** (with detailed daily blocks), and **Last Sync** timestamp.
*   **Sync Profile Control:** New `select` entity to configure cloud sync intervals (Energy saving, Normal, Fast, Super fast).
*   **Improved Stability & Reliability:** Significant fixes for API communication, `syncVersion` handling, WebSocket reconnection logic, and concurrent command serialization (`asyncio.Lock`).
*   **HA Compliance:** Adopts modern Home Assistant standards like `DeviceInfo`, `has_entity_name`, `entity_category`, `state_class`, and structured logging.
*   **Credential Management:** Adds `reconfigure` and `reauth` flows for updating credentials from the UI.

### v0.4.7

*   **Fixed issue #4:** Authentication failures caused by Finder's auth server rejecting `aiohttp`'s default User-Agent.
*   Added explicit User-Agent header to all requests.

---

## Credits and Thanks

This significant update to the Finder Bliss Home Assistant integration was made possible by the dedicated work and contributions from the community.

*   **@marl1w** for the extensive development and feature enhancements in this Pull Request, greatly expanding BLISS1 support, improving reliability, and bringing the integration closer to Home Assistant's best practices. Your efforts are highly appreciated!
*   **@MarcoBischero** for identifying the root cause of the authentication failures in issue #4.
*   **@wolverrinester** and **@aktasway-it** for their valuable testing and confirmation of the fix for issue #4.

Your contributions are essential to the continuous improvement of this project!

---

## Contributing  
  
Contributions to this project are welcome! If you'd like to help develop features or improve functionality, please fork the repository and create a pull request.  

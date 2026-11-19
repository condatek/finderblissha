# Changelog

## v0.5.20

* **Home Assistant Marketplace** installation instructions and thermostat category metadata for the shared Marketplace and HACS catalog.
* **BLISS2 availability:** mark a thermostat unavailable when Finder reports a connection error or no check-in is observed for 25 minutes. A Home Assistant restart starts a new 25-minute observation window.
* **BLISS2 manual mode:** interpret device-reported mode 2 as manual. Thanks to [@Mangillone](https://github.com/Mangillone) for the patch and hardware observations in [#15](https://github.com/condatek/finderblissha/issues/15).

## v0.5.14

* **BLISS1 per-device duration:** configure and restore each thermostat’s override duration independently, and inspect its active cloud override in the control’s attributes.

## v0.5.13

* **BLISS1 manual duration:** configure a timed override or indefinite manual mode, and recognize indefinite manual settings made in the Finder app.

## v0.5.12

This stable release includes the BLISS2 command and state fixes from `0.5.11-testing1` and `0.5.11-testing2`; the `0.5.11` series was prerelease-only. Command handling in `0.5.11-testing2` was successfully tested on a physical BLISS2.

* **Multiple thermostats:** command dispatch and confirmation check freshness for the target device only. Missing or older snapshots for another thermostat no longer block a fresh target; cached target data still cannot authorize or confirm a write.
* **Validation:** all 156 automated tests pass, including eight new cases for missing or older target and unrelated-device snapshots.

## v0.5.11-testing2 (pre-release)

* **BLISS2 command reconciliation:** send each command once, then perform up to ten confirmation reads, 1.5 seconds apart, with an overall 45-second verification limit. A missing ACK also triggers read-back rather than replaying a potentially applied write. Exhausting confirmation reports an uncertain outcome, not proof that the thermostat rejected the command.
* **Consistent state:** polling and writes share a transaction lock; older device versions cannot overwrite newer snapshots. Mode, `operating_mode`, presets and manual target temperature use cloud settings while hardware measurements catch up. Cloud confirmation does not prove physical delivery.
* **Temperature from OFF:** send MANUAL and the requested temperature together, avoiding an intermediate mode-only command.
* **WebSocket handling:** bound sync and handshake waits, ignore mismatched operation IDs when supplied, and recover cleanly from closed connections.

* **Validation:** all 148 automated tests pass, including delayed confirmation, lost acknowledgements, concurrent polling and temperature changes from OFF. Physical BLISS2 validation is still pending.

## v0.5.11-testing1 (pre-release)

*   **Fresh cloud state before skipping commands:** schedule writes and switching to AUTO now bypass the snapshot cache before deciding that no write is needed. Changes made through the Finder app are respected, and unavailable or partial cloud responses fail instead of reporting success from cached state.
*   **Safer diagnostic capture:** centralized JSON decoding handles leading whitespace and redacts malformed or undecodable serialized settings and schedules. Capture errors no longer include exception details that could expose raw payload values.
*   **BLISS2 command acknowledgements:** wait up to 15 seconds for an ACK across all intervening frames, replacing the 3-second per-frame wait and frame-count limit for BLISS2. BLISS1 uses a 3-second overall acknowledgement budget. Reset the websocket after an ACK timeout or connection error, and bound follow-up response draining. Commands still require cloud settings read-back before reporting success.
*   **BLISS2 HVAC mode display:** after confirmation, show the mode held in cloud settings while the thermostat's own echo catches up, preventing OFF from bouncing back to HEAT. Pending commands retain priority, and `operating_mode` continues to expose the device-reported mode. These changes address the problems reported and locally patched by [**@Mangillone**](https://github.com/Mangillone) in [#16](https://github.com/condatek/finderblissha/issues/16); physical-device confirmation is pending.
*   Added regression tests covering BLISS1, BLISS2, Home Assistant service calls, delayed and missing acknowledgements, HVAC mode display and capture redaction; all 133 tests pass.

## v0.5.10

*   **BLISS2 schedules and battery reporting:** includes the `finderblissha.set_schedule` service, device-shaped schedule set points, improved target-temperature display, a model-specific battery estimate and a Battery voltage diagnostic sensor, contributed by [**@Airbloomer**](https://github.com/Airbloomer) in [#17](https://github.com/condatek/finderblissha/pull/17). See v0.5.7-v0.5.9 below for implementation details. The schedule service replaces the active weekly schedule; temperatures are rounded to 0.5 °C and limited to 5-20 °C.
*   **Diagnostics and validation:** includes opt-in state capture, service descriptions, English translations, unit tests and CI checks for tests, HACS and hassfest, also contributed by @Airbloomer in #17. Battery percentages remain approximate.
*   **BLISS1 sync profiles:** corrected the documented intervals to **30 / 15 / 5 / 1 minutes**, thanks to [**@LorenzoRogai**](https://github.com/LorenzoRogai) in [#18](https://github.com/condatek/finderblissha/pull/18), and clarified that these profiles apply to BLISS1 only.
*   **Changelog:** restored the missing v0.5.6 entry and contributor credits to @marl1w and @7AC.
*   **Branding:** added integration icon and logo assets for local branding in Home Assistant 2026.3+, and displayed the logo in the README.

## v0.5.9

*   **Fix Bliss 2 battery level:** it was calibrated for the BLISS1's 2S2P pack, so every Bliss 2 read 100%. It now uses a 3S alkaline curve, and an implausible reading shows as unknown.
*   New **Battery voltage** diagnostic sensor with the raw reading.
*   The state capture includes `measures.batteryLevel`.

## v0.5.8

*   **Fix `set_schedule` on Bliss 2:** set points are now written in the shape the device reports (`{"unit": "C", "value": 190}` on a Bliss 2, not a bare `190`). A schedule identical to the current one is recognised as such, so nothing is sent.
*   The target temperature in schedule mode now reads dict-shaped schedule set points too.
*   **Opt-in state capture** for diagnosing writes: see [Notes](README.md#notes).

## v0.5.7

*   **New service `finderblissha.set_schedule`:** writes the active schedule from time blocks (one list for every day, or one per day), then switches to AUTO. It is idempotent and confirmed against the server.
*   Adds `services.yaml`, English translations and unit tests.

## v0.5.6

*   **WebSocket resilience:** improved connection reliability on weak networks by automatically resetting and reconnecting polling, reducing unavailable states and the need for manual reloads. (by [**@marl1w**](https://github.com/marl1w))
*   **Concurrent commands:** fixed execution failures when sending commands to multiple devices at the same time, for example through automations. (by [**@marl1w**](https://github.com/marl1w))
*   **OFF target temperature:** aligned OFF mode with the official Finder app: 35 °C in SUMMER and 5 °C in WINTER. (by [**@marl1w**](https://github.com/marl1w))
*   **Local schedule resolution:** added local resolution of scheduled set points in AUTO mode. (by [**@marl1w**](https://github.com/marl1w))
*   **Stale device removal:** added support for removing stale or orphaned thermostat devices from the Home Assistant UI when deleted from the Finder account. (by [**@marl1w**](https://github.com/marl1w))
*   **Schedule sensor:** fixed a `TypeError` when `setPoint` data is formatted as a dictionary. (by [**@7AC**](https://github.com/7AC))

Thanks to [**@marl1w**](https://github.com/marl1w) and [**@7AC**](https://github.com/7AC) for these contributions!

## v0.5.0

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

## v0.4.7

*   **Fixed issue #4:** Authentication failures caused by Finder's auth server rejecting `aiohttp`'s default User-Agent.
*   Added explicit User-Agent header to all requests.

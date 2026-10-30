"""Opt-in capture of what changes in device state, for working out writes.

Off unless the dedicated logger is set to debug explicitly, e.g. from
Developer tools:

    action: logger.set_level
    data:
      custom_components.finderblissha.capture: debug

Debug on the integration's own logger does not turn it on: the level is
pinned to WARNING here until set by name. Then:

- the first sync logs each device's state, flattened to path = value;
- every later sync logs only the paths that changed;
- every write logs the paths it changes against the last sync, and the
  fields of the server's answer.

Device identifiers, names, account data and anything resembling them are
redacted, and devices are labelled by position and model only. Measures are
reduced to the few fields that matter for commands. Payload sizes are
bounded. Nothing is logged with the logger at its default level.
"""

from __future__ import annotations

import json
import logging
import re

CAPTURE_LOGGER_NAME = "custom_components.finderblissha.capture"
_LOGGER = logging.getLogger(CAPTURE_LOGGER_NAME)
_LOGGER.setLevel(logging.WARNING)
_LOGGER.propagate = True

REDACTED = "<redacted>"
# Key names that can identify a person, an account, a place or a device.
_SENSITIVE_KEY = re.compile(
    r"(name|serial|handle|house|gateway|user|mail|token|pass|secret|key|ssid|"
    r"mac|ip$|ipaddr|address|lat|lon|gps|phone|owner|account|client|^id$|id$)",
    re.IGNORECASE,
)
# Values that look like an e-mail address or a long opaque identifier.
_SENSITIVE_VALUE = re.compile(r"@|^[0-9a-fA-F-]{16,}$|^[A-Za-z0-9+/=_-]{32,}$")
# Device-level fields worth seeing; everything else at that level is dropped.
_DEVICE_FIELDS = ("tag", "status", "syncVersion", "isDeleted", "channel", "role", "tz", "lastUpdate")
_MEASURE_FIELDS = ("mode", "status", "setPoint", "loggerSetPoint")
_ACK_DROP = ("serverPayload", "clientPayload")
MAX_LINES = 400
MAX_VALUE = 120

# Keyed by the device handle, which is never logged; labels are positional.
_last: dict[str, dict[str, str]] = {}
_labels: dict[str, str] = {}


def enabled() -> bool:
    return _LOGGER.isEnabledFor(logging.DEBUG)


def _load(value):
    if isinstance(value, str) and value[:1] in ("{", "["):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _scalar(key: str, value) -> str:
    if _SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        return REDACTED
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= MAX_VALUE else text[:MAX_VALUE] + "..."


def _flatten(value, path: str, out: dict[str, str], key: str = "") -> None:
    value = _load(value)
    if key and _SENSITIVE_KEY.search(key):
        out[path] = REDACTED
    elif isinstance(value, dict):
        if not value:
            out[path] = "{}"
        for k, v in value.items():
            _flatten(v, f"{path}.{k}" if path else str(k), out, str(k))
    elif isinstance(value, list):
        if not value:
            out[path] = "[]"
        for i, v in enumerate(value):
            _flatten(v, f"{path}[{i}]", out, key)
    else:
        out[path] = _scalar(key, value)


def device_view(device: dict) -> dict[str, str]:
    """Flatten one raw device entry (API camelCase) to redacted path = value."""
    out: dict[str, str] = {}
    for field in _DEVICE_FIELDS:
        if field in device:
            _flatten(device[field], field, out, field)
    _flatten(device.get("settings"), "settings", out)
    _flatten(device.get("schedules"), "schedules", out)
    measures = _load(device.get("measures"))
    if isinstance(measures, dict):
        for field in _MEASURE_FIELDS:
            if field in measures:
                _flatten(measures[field], f"measures.{field}", out, field)
    return out


def _key(device: dict) -> str:
    return str(device.get("handle") or device.get("serialNumber") or "")


def _label(device: dict, index: int | None = None) -> str:
    key = _key(device)
    if key not in _labels:
        _labels[key] = f"device{len(_labels) + 1 if index is None else index + 1}({device.get('tag', '?')})"
    return _labels[key]


def _emit(prefix: str, lines: list[str]) -> None:
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES] + [f"... {len(lines) - MAX_LINES} more lines"]
    _LOGGER.debug("%s\n%s", prefix, "\n".join(lines) if lines else "(no changes)")


def _diff(old: dict[str, str], new: dict[str, str]) -> list[str]:
    lines = []
    for path in sorted(set(old) | set(new)):
        before, after = old.get(path), new.get(path)
        if before != after:
            lines.append(f"  {path}: {before if before is not None else '(absent)'} -> "
                         f"{after if after is not None else '(absent)'}")
    return lines


def _devices(payload) -> list:
    data = _load(payload)
    devices = data.get("devices", []) if isinstance(data, dict) else []
    return [d for d in devices if isinstance(d, dict)]


def on_sync(payload) -> None:
    """Log a server payload: the full state once, then what changed."""
    if not enabled():
        return
    try:
        for index, device in enumerate(_devices(payload)):
            label = _label(device, index)
            view = device_view(device)
            previous = _last.get(_key(device))
            if previous is None:
                _emit(f"capture sync {label} initial state",
                      [f"  {p} = {v}" for p, v in sorted(view.items())])
            else:
                _emit(f"capture sync {label} changes", _diff(previous, view))
            _last[_key(device)] = view
    except Exception:  # noqa: BLE001 - capture must never break a sync
        _LOGGER.debug("capture: could not read sync payload", exc_info=True)


def on_send(device: dict) -> None:
    """Log what an outgoing write changes against the last synced state."""
    if not enabled():
        return
    try:
        view = device_view(device)
        _emit(f"capture send {_label(device)} changes against last sync",
              _diff(_last.get(_key(device), {}), view))
    except Exception:  # noqa: BLE001
        _LOGGER.debug("capture: could not read outgoing payload", exc_info=True)


def on_answer(frame: dict) -> None:
    """Log the fields of a server answer to a write, without payloads."""
    if not enabled():
        return
    try:
        out: dict[str, str] = {}
        _flatten(frame.get("target"), "target", out, "target")
        for i, arg in enumerate(frame.get("arguments") or []):
            if isinstance(arg, dict):
                for k, v in arg.items():
                    if k in _ACK_DROP:
                        out[f"arguments[{i}].{k}"] = "<payload>" if v else json.dumps(v)
                    else:
                        _flatten(v, f"arguments[{i}].{k}", out, k)
        _emit("capture answer", [f"  {p} = {v}" for p, v in sorted(out.items())])
    except Exception:  # noqa: BLE001
        _LOGGER.debug("capture: could not read server answer", exc_info=True)

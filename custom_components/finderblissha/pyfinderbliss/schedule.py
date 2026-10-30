"""Build the automaticSchedule days a Bliss thermostat runs in AUTO mode.

The device stores one entry per weekday, 1=Monday..7=Sunday:

    {"day": 1, "setPoints": [{"hour": 0, "minute": 0, "setPoint": 190}, ...]}

Each set point holds from its own time until the next one, in tenths of a
degree C. Callers describe a day as contiguous time blocks instead, which is
easier to check: the first block starts at 00:00, each one ends where the
next starts, and the last one ends at 24:00.
"""

from __future__ import annotations

import logging
import math

_LOGGER = logging.getLogger(__name__)

MIN_TEMP = 5.0
MAX_TEMP = 20.0
TEMP_STEP = 0.5

DAY_NUMBERS = {
    "mon": 1, "monday": 1,
    "tue": 2, "tuesday": 2,
    "wed": 3, "wednesday": 3,
    "thu": 4, "thursday": 4,
    "fri": 5, "friday": 5,
    "sat": 6, "saturday": 6,
    "sun": 7, "sunday": 7,
}

_END_OF_DAY = 24 * 60


class ScheduleError(ValueError):
    """The requested schedule cannot be written as given."""


def parse_time(value) -> int:
    """Return minutes since midnight for "HH:MM" (or "HH:MM:SS" with :00).

    An integer is taken as minutes since midnight. YAML 1.1 reads an unquoted
    22:00 as the base-60 number 1320, which is exactly that, while 05:00 stays
    a string because of its leading zero; accepting both keeps unquoted
    service calls working.
    """
    if isinstance(value, bool):
        raise ScheduleError(f"Invalid time {value!r}")
    if isinstance(value, int):
        minutes = value
    elif isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
            raise ScheduleError(f"Invalid time {value!r}, expected HH:MM")
        if len(parts) == 3 and int(parts[2]) != 0:
            raise ScheduleError(f"Invalid time {value!r}, seconds must be 00")
        hour, minute = int(parts[0]), int(parts[1])
        if minute > 59:
            raise ScheduleError(f"Invalid time {value!r}")
        minutes = hour * 60 + minute
    else:
        raise ScheduleError(f"Invalid time {value!r}, expected HH:MM")
    if not 0 <= minutes <= _END_OF_DAY:
        raise ScheduleError(f"Invalid time {value!r}, outside 00:00-24:00")
    return minutes


def clamp_temp(value) -> float:
    """Round to the nearest 0.5 C (halves up) and clamp to MIN_TEMP..MAX_TEMP."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ScheduleError(f"Invalid temperature {value!r}")
    stepped = math.floor(value / TEMP_STEP + 0.5) * TEMP_STEP
    clamped = min(MAX_TEMP, max(MIN_TEMP, stepped))
    if clamped != value:
        _LOGGER.warning("Schedule temperature %s C written as %s C", value, clamped)
    return clamped


def day_number(key) -> int:
    """Map "mon"/"monday"/1 (or "1") to 1..7."""
    if isinstance(key, bool):
        raise ScheduleError(f"Invalid day {key!r}")
    if isinstance(key, str):
        name = key.strip().lower()
        if name in DAY_NUMBERS:
            return DAY_NUMBERS[name]
        if not name.isdigit():
            raise ScheduleError(f"Invalid day {key!r}")
        key = int(name)
    if isinstance(key, int) and 1 <= key <= 7:
        return key
    raise ScheduleError(f"Invalid day {key!r}, expected mon..sun or 1..7")


def build_day(day: int, blocks: list) -> dict:
    """Turn one day's contiguous blocks into its set points."""
    if not blocks:
        raise ScheduleError(f"Day {day} has no blocks")

    set_points = []
    expected_start = 0
    for block in blocks:
        if not isinstance(block, dict) or not {"from", "to", "temp"} <= block.keys():
            raise ScheduleError(f"Day {day}: each block needs from, to and temp")
        start = parse_time(block["from"])
        end = parse_time(block["to"])
        if start != expected_start:
            raise ScheduleError(
                f"Day {day}: block from {block['from']!r} must start where the "
                f"previous one ends ({expected_start // 60:02d}:{expected_start % 60:02d})"
            )
        if end <= start:
            raise ScheduleError(f"Day {day}: block {block['from']!r}-{block['to']!r} ends before it starts")
        set_points.append({
            "hour": start // 60,
            "minute": start % 60,
            "setPoint": round(clamp_temp(block["temp"]) * 10),
        })
        expected_start = end

    if expected_start != _END_OF_DAY:
        raise ScheduleError(f"Day {day}: the last block must end at 24:00")
    return {"day": day, "setPoints": set_points}


def build_schedule_days(blocks: list | None = None, days: dict | None = None) -> list:
    """Build all seven days, from one block list or from one list per day.

    Exactly one of blocks (applied to every day) or days (a mapping with all
    seven weekdays) must be given.
    """
    if (blocks is None) == (days is None):
        raise ScheduleError("Give either blocks or days, not both")

    if blocks is not None:
        return [build_day(day, blocks) for day in range(1, 8)]

    if not isinstance(days, dict):
        raise ScheduleError("days must map each weekday to its blocks")
    by_number: dict[int, list] = {}
    for key, day_blocks in days.items():
        number = day_number(key)
        if number in by_number:
            raise ScheduleError(f"Day {key!r} is given twice")
        by_number[number] = day_blocks
    missing = [n for n in range(1, 8) if n not in by_number]
    if missing:
        raise ScheduleError(f"days must cover all seven weekdays; missing {missing}")
    return [build_day(day, by_number[day]) for day in range(1, 8)]

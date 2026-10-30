import pytest

from custom_components.finderblissha.pyfinderbliss.device_parser import (
    parse_battery_level,
    parse_battery_voltage,
)


@pytest.mark.parametrize("raw,expected", [(21, 0), (25, 44), (28, 78), (30, 100), (33, 100), (19, 0)])
def test_bliss1_2s2p_curve_is_unchanged(raw, expected):
    # (raw - 21) / 9 * 100, clamped: the upstream BLISS1 calibration.
    assert parse_battery_level(raw, "BLISS1") == expected
    assert parse_battery_level(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    (45, 100),  # 1.50 V/cell, fresh
    (46, 100),
    (42, 75),   # 1.40 V/cell
    (39, 35),   # 1.30 V/cell
    (38, 25),   # 1.267 V/cell
    (36, 10),   # 1.20 V/cell
    (33, 0),    # 1.10 V/cell, empty
    (30, 0),    # below cutoff, still a battery voltage
])
def test_bliss2_3s_alkaline_curve(raw, expected):
    assert parse_battery_level(raw, "BLISS2") == expected


def test_bliss2_one_dot_reads_below_30_percent():
    # The app drops to one dot on a BLISS1 below 1.275 V per cell; at that
    # per-cell voltage a 3S pack is 3.825 V.
    assert parse_battery_level(38.2, "BLISS2") < 30
    assert parse_battery_level(37, "BLISS2") < 30


@pytest.mark.parametrize("raw", [100, 60, 23, 0, None, "N/A", True])
def test_bliss2_implausible_readings_give_no_percentage(raw):
    assert parse_battery_level(raw, "BLISS2") == "N/A"


def test_dict_and_bare_readings():
    assert parse_battery_level({"value": 42}, "BLISS2") == 75
    assert parse_battery_voltage({"value": 42}) == 4.2
    assert parse_battery_voltage(29) == 2.9
    assert parse_battery_voltage({"unit": "V"}) is None
    assert parse_battery_voltage(None) is None

import pytest

from custom_components.finderblissha.pyfinderbliss.schedule import (
    ScheduleError,
    build_schedule_days,
    clamp_temp,
    parse_time,
)

from .conftest import APP_DAYS

OCCUPIED = [
    {"from": "00:00", "to": "05:00", "temp": 19.0},
    {"from": "05:00", "to": "22:00", "temp": 20.0},
    {"from": "22:00", "to": "24:00", "temp": 19.0},
]


def all_days(set_points):
    return [{"day": d, "setPoints": set_points} for d in range(1, 8)]


def test_occupied_matches_the_app_schedule_shape():
    assert build_schedule_days(blocks=OCCUPIED) == APP_DAYS


@pytest.mark.parametrize("temp,tenths", [(17, 170), (15, 150)])
def test_all_day_schedules(temp, tenths):
    days = build_schedule_days(blocks=[{"from": "00:00", "to": "24:00", "temp": temp}])
    assert days == all_days([{"hour": 0, "minute": 0, "setPoint": tenths}])


def test_per_day_lists_by_name_or_number():
    vacant = [{"from": "00:00", "to": "24:00", "temp": 15}]
    days = {"mon": OCCUPIED, "Tuesday": vacant, 3: vacant, "4": vacant,
            "fri": vacant, "sat": vacant, "sun": OCCUPIED}
    built = build_schedule_days(days=days)
    assert [d["day"] for d in built] == list(range(1, 8))
    assert built[0] == APP_DAYS[0]
    assert built[1]["setPoints"] == [{"hour": 0, "minute": 0, "setPoint": 150}]
    assert built[6]["setPoints"] == APP_DAYS[6]["setPoints"]


def test_unquoted_yaml_times_are_minutes():
    # YAML 1.1: 22:00 -> 1320, 24:00 -> 1440; 05:00 stays a string.
    blocks = [
        {"from": "00:00", "to": "05:00", "temp": 19},
        {"from": "05:00", "to": 1320, "temp": 20},
        {"from": 1320, "to": 1440, "temp": 19},
    ]
    assert build_schedule_days(blocks=blocks) == APP_DAYS


@pytest.mark.parametrize("value,expected", [
    (19.0, 19.0), (19.2, 19.0), (19.25, 19.5), (19.74, 19.5),
    (4, 5.0), (-3, 5.0), (20.4, 20.0), (25, 20.0), (35, 20.0),
])
def test_temps_round_to_half_and_clamp(value, expected):
    assert clamp_temp(value) == expected


def test_clamped_temps_reach_the_payload():
    days = build_schedule_days(blocks=[
        {"from": "00:00", "to": "12:30", "temp": 3},
        {"from": "12:30", "to": "24:00", "temp": 21.3},
    ])
    assert days[0]["setPoints"] == [
        {"hour": 0, "minute": 0, "setPoint": 50},
        {"hour": 12, "minute": 30, "setPoint": 200},
    ]


@pytest.mark.parametrize("blocks,message", [
    ([], "no blocks"),
    ([{"from": "01:00", "to": "24:00", "temp": 19}], "must start"),
    ([{"from": "00:00", "to": "12:00", "temp": 19}], "end at 24:00"),
    ([{"from": "00:00", "to": "12:00", "temp": 19}, {"from": "13:00", "to": "24:00", "temp": 19}], "must start"),
    ([{"from": "00:00", "to": "00:00", "temp": 19}], "ends before"),
    ([{"from": "00:00", "to": "24:00"}], "needs from, to and temp"),
    ([{"from": "00:00", "to": "25:00", "temp": 19}], "outside"),
    ([{"from": "00:00", "to": "12:61", "temp": 19}], "Invalid time"),
    ([{"from": "0:0:5", "to": "24:00", "temp": 19}], "seconds"),
    ([{"from": "noon", "to": "24:00", "temp": 19}], "Invalid time"),
    ([{"from": "00:00", "to": "24:00", "temp": float("nan")}], "Invalid temperature"),
    ([{"from": "00:00", "to": "24:00", "temp": True}], "Invalid temperature"),
])
def test_rejects_blocks_that_do_not_cover_the_day(blocks, message):
    with pytest.raises(ScheduleError, match=message):
        build_schedule_days(blocks=blocks)


def test_needs_exactly_one_of_blocks_or_days():
    with pytest.raises(ScheduleError, match="either"):
        build_schedule_days()
    with pytest.raises(ScheduleError, match="either"):
        build_schedule_days(blocks=OCCUPIED, days={"mon": OCCUPIED})


def test_per_day_needs_all_seven_once():
    six = {d: OCCUPIED for d in ("mon", "tue", "wed", "thu", "fri", "sat")}
    with pytest.raises(ScheduleError, match=r"missing \[7\]"):
        build_schedule_days(days=six)
    with pytest.raises(ScheduleError, match="twice"):
        build_schedule_days(days={**six, "sun": OCCUPIED, "7": OCCUPIED})
    with pytest.raises(ScheduleError, match="Invalid day"):
        build_schedule_days(days={**six, "funday": OCCUPIED})


def test_parse_time_accepts_time_selector_seconds():
    assert parse_time("05:30:00") == 330

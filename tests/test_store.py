import sqlite3

import pytest

from spotter.store import GarminRunAlreadyClaimed, Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "workouts.sqlite3")


def test_incomplete_records_persist_after_reopening(tmp_path):
    path = tmp_path / "workouts.sqlite3"
    record = Store(path).add("sessions", {"start_at": "2026-09-08T10:00:00-04:00"})
    assert Store(path).get("sessions", record["id"])["end_at"] is None


def test_individual_sets_preserve_zero_and_unknown(store):
    session = store.add("sessions", {})
    exercise = store.add("exercises", {"name": "Squat"})
    for order, weight in enumerate([None, 0, 20], 1):
        store.add(
            "strength_sets",
            {
                "workout_id": session["id"],
                "exercise_id": exercise["id"],
                "set_order": order,
                "reps": 8,
                "weight": weight,
                "weight_unit": "kg" if weight is not None else None,
                "effort_note": "Hard last rep",
            },
        )
    assert [row["weight"] for row in store.list("strength_sets")] == [None, 0, 20]


def test_correction_updates_only_supplied_fields(store):
    run = store.add("runs", {"distance": 5, "distance_unit": "km", "notes": "Treadmill"})
    result = store.update("runs", run["id"], {"distance": 6})
    assert (result["distance"], result["notes"], len(store.list("runs"))) == (6, "Treadmill", 1)


def test_explicit_null_clears_field(store):
    run = store.add("runs", {"notes": "Wrong note"})
    assert store.update("runs", run["id"], {"notes": None})["notes"] is None


@pytest.mark.parametrize(
    "table,data",
    [
        ("sessions", {"start_at": "2026-09-08T10:00:00"}),
        ("sessions", {"start_at": "2026-09-08T10:00:00Z", "end_at": "2026-09-08T09:00:00Z"}),
        ("runs", {"distance": -1, "distance_unit": "km"}),
        ("runs", {"distance": 5}),
        ("runs", {"distance": 5, "distance_unit": "yards"}),
        ("runs", {"duration_seconds": 0}),
        ("runs", {"max_speed": 12}),
        ("runs", {"reported_pace": 300, "pace_unit": "sec/km"}),
        ("runs", {"distance": float("nan"), "distance_unit": "km"}),
        ("strength_sets", {"reps": -1}),
        ("strength_sets", {"reps": 2.5}),
        ("strength_sets", {"weight": 0}),
        ("body_measurements", {"weight": 70}),
        ("exercises", {"name": "   "}),
        ("runs", {"typo": 3}),
    ],
)
def test_invalid_records_are_not_saved(store, table, data):
    with pytest.raises(ValueError):
        store.add(table, data)
    assert store.list(table) == []


def test_failed_correction_preserves_record(store):
    run = store.add("runs", {"distance": 5, "distance_unit": "km"})
    with pytest.raises(ValueError):
        store.update("runs", run["id"], {"distance_unit": None})
    assert store.get("runs", run["id"])["distance_unit"] == "km"


def test_unknown_reference_rejected(store):
    with pytest.raises(sqlite3.IntegrityError):
        store.add("runs", {"workout_id": 999})
    assert store.list("runs") == []


def test_duplicate_set_order_rejected(store):
    session = store.add("sessions", {})
    exercise = store.add("exercises", {"name": "Squat"})
    data = {"workout_id": session["id"], "exercise_id": exercise["id"], "set_order": 1}
    store.add("strength_sets", data)
    with pytest.raises(sqlite3.IntegrityError):
        store.add("strength_sets", data)


def test_missing_record_cannot_be_corrected(store):
    with pytest.raises(KeyError):
        store.update("runs", 999, {"notes": "Correction"})


def test_unknown_table_rejected(store):
    with pytest.raises(ValueError):
        store.list("runs; DROP TABLE runs")


@pytest.mark.parametrize(
    "distance,unit,seconds,pace,speed",
    [
        (5, "km", 1800, 360, 10),
        (1, "mi", 600, 600 / 1.609344, 9.656064),
        (400, "m", 120, 300, 12),
    ],
)
def test_average_metrics(store, distance, unit, seconds, pace, speed):
    run = store.add(
        "runs",
        {
            "distance": distance,
            "distance_unit": unit,
            "duration_seconds": seconds,
        },
    )
    assert run["average_pace_seconds_per_km"] == pytest.approx(pace)
    assert run["average_speed_kmh"] == pytest.approx(speed)


@pytest.mark.parametrize("data", [{}, {"distance": 0, "distance_unit": "km"}])
def test_missing_or_zero_distance_has_no_pace(store, data):
    assert store.add("runs", data)["average_pace_seconds_per_km"] is None


def test_reported_metrics_are_separate_from_average(store):
    run = store.add(
        "runs",
        {
            "reported_pace": 300,
            "pace_unit": "sec/km",
            "pace_kind": "current",
            "max_speed": 14,
            "speed_unit": "km/h",
            "distance": 5,
            "distance_unit": "km",
            "duration_seconds": 1800,
        },
    )
    assert (run["reported_pace"], run["average_pace_seconds_per_km"], run["max_speed"]) == (
        300,
        360,
        14,
    )


def test_filter_sets_by_workout(store):
    first = store.add("sessions", {})
    second = store.add("sessions", {})
    store.add("strength_sets", {"workout_id": first["id"], "reps": 8})
    store.add("strength_sets", {"workout_id": second["id"], "reps": 10})
    assert [row["reps"] for row in store.list("strength_sets", workout_id=first["id"])] == [8]


def test_garmin_import_rolls_back_new_session_and_run_on_invalid_provenance(store):
    with pytest.raises(ValueError):
        store.save_garmin_activity(
            session_id=None,
            session_values={"start_at": "2026-09-11T11:30:00Z"},
            run_id=None,
            run_values={"distance": 5, "distance_unit": "km"},
            garmin_values={"activity_type": None},
        )

    assert store.list("sessions") == []
    assert store.list("runs") == []
    assert store.list("garmin_activities") == []


def test_garmin_import_rolls_back_existing_run_update_on_invalid_provenance(store):
    session = store.add("sessions", {"start_at": "2026-09-11T11:30:00Z"})
    run = store.add("runs", {"workout_id": session["id"], "notes": "Keep me"})

    with pytest.raises(ValueError):
        store.save_garmin_activity(
            session_id=session["id"],
            session_values={},
            run_id=run["id"],
            run_values={"distance": 5, "distance_unit": "km"},
            garmin_values={"activity_type": None},
        )

    assert store.get("runs", run["id"])["distance"] is None
    assert store.get("runs", run["id"])["notes"] == "Keep me"


def test_stale_run_selection_cannot_be_claimed_by_second_garmin_activity(store):
    session = store.add("sessions", {"start_at": "2026-09-11T11:30:00Z"})
    run = store.add("runs", {"workout_id": session["id"]})
    provenance = {
        "activity_type": "running",
        "start_at": "2026-09-11T11:30:00Z",
        "imported_at": "2026-09-11T12:00:00Z",
        "raw_file_path": "/private/activity.zip",
        "details_json": "{}",
    }
    store.save_garmin_activity(
        session_id=session["id"],
        session_values={},
        run_id=run["id"],
        run_values={"distance": 5, "distance_unit": "km"},
        garmin_values=provenance | {"garmin_activity_id": "111"},
    )

    with pytest.raises(GarminRunAlreadyClaimed):
        store.save_garmin_activity(
            session_id=session["id"],
            session_values={},
            run_id=run["id"],
            run_values={"distance": 2, "distance_unit": "km"},
            garmin_values=provenance | {"garmin_activity_id": "222"},
        )

    assert store.get("runs", run["id"])["distance"] == 5
    assert len(store.list("garmin_activities")) == 1

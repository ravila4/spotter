import json
import sqlite3
import stat
from datetime import date

import pytest
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from spotter.garmin import sync_activities, sync_daily_steps
from spotter.store import GarminActivityAlreadyImported, Store


class FakeGarmin:
    def __init__(self, activities):
        self.activities = activities
        self.downloaded = []

    def get_activities_by_date(self, startdate, enddate):
        return self.activities

    def get_activity_details(self, activity_id):
        return {"activityId": activity_id, "samples": [{"heartRate": 142}]}

    def download_original_activity(self, activity_id):
        self.downloaded.append(activity_id)
        return b"original-fit-zip"


def running_activity():
    return {
        "activityId": 12345,
        "activityName": "Morning Run",
        "activityType": {"typeKey": "running"},
        "startTimeGMT": "2026-09-11 11:30:00",
        "distance": 5000.0,
        "duration": 1800.0,
        "averageHR": 148.0,
        "maxHR": 171.0,
        "calories": 420.0,
    }


def test_sync_creates_run_with_garmin_provenance(tmp_path):
    store = Store(tmp_path / "spotter.sqlite3")
    client = FakeGarmin([running_activity()])

    result = sync_activities(
        store,
        client,
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 11),
        archive_dir=tmp_path / "garmin",
    )

    run = store.list("runs")[0]
    imported = store.list("garmin_activities")[0]
    assert result == {"imported": 1, "skipped": 0, "failures": []}
    assert (run["distance"], run["distance_unit"], run["duration_seconds"]) == (5.0, "km", 1800.0)
    assert run["duration_kind"] is None
    assert (imported["average_heart_rate"], imported["max_heart_rate"]) == (148.0, 171.0)
    assert imported["run_id"] == run["id"]
    assert json.loads(imported["details_json"])["samples"][0]["heartRate"] == 142
    archives = list((tmp_path / "garmin").glob("12345-*.zip"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == b"original-fit-zip"


def test_sync_is_idempotent(tmp_path):
    store = Store(tmp_path / "spotter.sqlite3")
    client = FakeGarmin([running_activity()])
    options = {
        "start_date": date(2026, 9, 10),
        "end_date": date(2026, 9, 11),
        "archive_dir": tmp_path / "garmin",
    }

    sync_activities(store, client, **options)
    result = sync_activities(store, client, **options)

    assert result == {"imported": 0, "skipped": 1, "failures": []}
    assert len(store.list("sessions")) == 1
    assert len(store.list("runs")) == 1
    assert client.downloaded == ["12345"]


def test_sync_enriches_nearby_existing_run(tmp_path):
    store = Store(tmp_path / "spotter.sqlite3")
    session = store.add("sessions", {"start_at": "2026-09-11T07:28:00-04:00"})
    existing = store.add("runs", {"workout_id": session["id"], "notes": "Felt easy"})

    sync_activities(
        store,
        FakeGarmin([running_activity()]),
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 11),
        archive_dir=tmp_path / "garmin",
    )

    runs = store.list("runs")
    assert len(runs) == 1
    assert runs[0]["id"] == existing["id"]
    assert (runs[0]["distance"], runs[0]["notes"]) == (5.0, "Felt easy")


def test_failed_activity_remains_retryable(tmp_path):
    class BrokenGarmin(FakeGarmin):
        def get_activity_details(self, activity_id):
            raise OSError("Garmin timed out")

    store = Store(tmp_path / "spotter.sqlite3")
    options = {
        "start_date": date(2026, 9, 10),
        "end_date": date(2026, 9, 11),
        "archive_dir": tmp_path / "garmin",
    }

    first = sync_activities(store, BrokenGarmin([running_activity()]), **options)
    second = sync_activities(store, FakeGarmin([running_activity()]), **options)

    assert first == {
        "imported": 0,
        "skipped": 0,
        "failures": [{"garmin_activity_id": "12345", "reason": "Garmin timed out"}],
    }
    assert second == {"imported": 1, "skipped": 0, "failures": []}
    assert len(store.list("garmin_activities")) == 1


def test_daily_steps_preserve_zero_and_update_same_date(tmp_path):
    class StepGarmin:
        total = 0

        def get_stats(self, day):
            return {"calendarDate": day, "totalSteps": self.total, "stepGoal": 8000}

    store = Store(tmp_path / "spotter.sqlite3")
    client = StepGarmin()

    first = sync_daily_steps(
        store, client, start_date=date(2026, 9, 11), end_date=date(2026, 9, 11)
    )
    client.total = 2345
    second = sync_daily_steps(
        store, client, start_date=date(2026, 9, 11), end_date=date(2026, 9, 11)
    )

    rows = store.list("garmin_daily_steps")
    assert first == {"created": 1, "updated": 0, "failures": []}
    assert second == {"created": 0, "updated": 1, "failures": []}
    assert len(rows) == 1
    assert (rows[0]["day"], rows[0]["total_steps"], rows[0]["step_goal"]) == (
        "2026-09-11",
        2345,
        8000,
    )


def test_daily_step_failure_identifies_retryable_date(tmp_path):
    class BrokenStepGarmin:
        def get_stats(self, day):
            raise OSError("Garmin timed out")

    result = sync_daily_steps(
        Store(tmp_path / "spotter.sqlite3"),
        BrokenStepGarmin(),
        start_date=date(2026, 9, 11),
        end_date=date(2026, 9, 11),
    )

    assert result == {
        "created": 0,
        "updated": 0,
        "failures": [{"day": "2026-09-11", "reason": "Garmin timed out"}],
    }


def test_two_nearby_garmin_runs_get_distinct_runs(tmp_path):
    first = running_activity()
    second = running_activity() | {
        "activityId": 67890,
        "startTimeGMT": "2026-09-11 11:40:00",
        "distance": 2000.0,
    }
    store = Store(tmp_path / "spotter.sqlite3")

    result = sync_activities(
        store,
        FakeGarmin([first, second]),
        start_date=date(2026, 9, 11),
        end_date=date(2026, 9, 11),
        archive_dir=tmp_path / "garmin",
    )

    imports = store.list("garmin_activities")
    assert result["imported"] == 2
    assert len(store.list("sessions")) == 2
    assert len(store.list("runs")) == 2
    assert imports[0]["run_id"] != imports[1]["run_id"]


def test_garmin_run_does_not_attach_to_strength_only_session(tmp_path):
    store = Store(tmp_path / "spotter.sqlite3")
    session = store.add("sessions", {"start_at": "2026-09-11T07:28:00-04:00"})
    exercise = store.add("exercises", {"name": "Squat"})
    store.add(
        "strength_sets",
        {"workout_id": session["id"], "exercise_id": exercise["id"], "set_order": 1},
    )

    sync_activities(
        store,
        FakeGarmin([running_activity()]),
        start_date=date(2026, 9, 11),
        end_date=date(2026, 9, 11),
        archive_dir=tmp_path / "garmin",
    )

    assert len(store.list("sessions")) == 2
    assert store.list("runs")[0]["workout_id"] != session["id"]


def test_fit_archives_are_owner_only_even_when_directory_exists(tmp_path):
    archive_dir = tmp_path / "garmin"
    archive_dir.mkdir(mode=0o755)

    sync_activities(
        Store(tmp_path / "spotter.sqlite3"),
        FakeGarmin([running_activity()]),
        start_date=date(2026, 9, 11),
        end_date=date(2026, 9, 11),
        archive_dir=archive_dir,
    )

    assert stat.S_IMODE(archive_dir.stat().st_mode) == 0o700
    archive = next(archive_dir.glob("12345-*.zip"))
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600


def test_activity_id_cannot_escape_archive_directory(tmp_path):
    activity = running_activity() | {"activityId": "../escape"}
    store = Store(tmp_path / "spotter.sqlite3")

    result = sync_activities(
        store,
        FakeGarmin([activity]),
        start_date=date(2026, 9, 11),
        end_date=date(2026, 9, 11),
        archive_dir=tmp_path / "garmin",
    )

    assert result["failures"][0]["garmin_activity_id"] == "../escape"
    assert not (tmp_path / "escape.zip").exists()
    assert store.list("sessions") == []


def test_connection_error_is_attributed_and_later_activity_continues(tmp_path):
    class FlakyGarmin(FakeGarmin):
        def get_activity_details(self, activity_id):
            if activity_id == "12345":
                raise GarminConnectConnectionError("timed out")
            return super().get_activity_details(activity_id)

    second = running_activity() | {"activityId": 67890, "startTimeGMT": "2026-09-11 13:00:00"}
    store = Store(tmp_path / "spotter.sqlite3")

    result = sync_activities(
        store,
        FlakyGarmin([running_activity(), second]),
        start_date=date(2026, 9, 11),
        end_date=date(2026, 9, 11),
        archive_dir=tmp_path / "garmin",
    )

    assert result["imported"] == 1
    assert result["failures"] == [{"garmin_activity_id": "12345", "reason": "timed out"}]


@pytest.mark.parametrize(
    "error,expected",
    [
        (GarminConnectAuthenticationError("expired"), "garmin-login"),
        (GarminConnectTooManyRequestsError("slow down"), "retry later"),
    ],
)
def test_account_level_errors_stop_with_recovery_guidance(tmp_path, error, expected):
    class BlockedGarmin(FakeGarmin):
        def get_activities_by_date(self, startdate, enddate):
            raise error

    with pytest.raises(ValueError, match=expected):
        sync_activities(
            Store(tmp_path / "spotter.sqlite3"),
            BlockedGarmin([]),
            start_date=date(2026, 9, 11),
            end_date=date(2026, 9, 11),
            archive_dir=tmp_path / "garmin",
        )


def test_database_failure_leaves_no_archive_or_partial_records(tmp_path, monkeypatch):
    store = Store(tmp_path / "spotter.sqlite3")
    monkeypatch.setattr(
        store,
        "save_garmin_activity",
        lambda **kwargs: (_ for _ in ()).throw(sqlite3.IntegrityError("forced failure")),
    )

    result = sync_activities(
        store,
        FakeGarmin([running_activity()]),
        start_date=date(2026, 9, 11),
        end_date=date(2026, 9, 11),
        archive_dir=tmp_path / "garmin",
    )

    assert result["failures"] == [{"garmin_activity_id": "12345", "reason": "forced failure"}]
    assert list((tmp_path / "garmin").glob("12345-*.zip")) == []
    assert store.list("sessions") == []


def test_losing_same_activity_import_does_not_delete_winner_archive(tmp_path, monkeypatch):
    archive_dir = tmp_path / "garmin"
    archive_dir.mkdir()
    winner = archive_dir / "12345-winner.zip"
    winner.write_bytes(b"winner")
    store = Store(tmp_path / "spotter.sqlite3")
    monkeypatch.setattr(
        store,
        "save_garmin_activity",
        lambda **kwargs: (_ for _ in ()).throw(GarminActivityAlreadyImported("claimed")),
    )

    result = sync_activities(
        store,
        FakeGarmin([running_activity()]),
        start_date=date(2026, 9, 11),
        end_date=date(2026, 9, 11),
        archive_dir=archive_dir,
    )

    assert result == {"imported": 0, "skipped": 1, "failures": []}
    assert winner.read_bytes() == b"winner"
    assert list(archive_dir.iterdir()) == [winner]

import copy
import sqlite3
import stat
from datetime import UTC, date, datetime

import pytest
from garminconnect import GarminConnectConnectionError, GarminConnectTooManyRequestsError

from spotter.health import health_dates, parse_body_battery, parse_vo2, sync_health
from spotter.store import Store

DAY = date(2025, 1, 2)
START = datetime(2025, 1, 3, 1, tzinfo=UTC)
END = datetime(2025, 1, 3, 1, 1, tzinfo=UTC)


def battery(level=42):
    return [
        {
            "date": DAY.isoformat(),
            "charged": 12,
            "drained": 8,
            "bodyBatteryValueDescriptorDTOList": [
                {
                    "bodyBatteryValueDescriptorIndex": 1,
                    "bodyBatteryValueDescriptorKey": "timestamp",
                },
                {
                    "bodyBatteryValueDescriptorIndex": 0,
                    "bodyBatteryValueDescriptorKey": "bodyBatteryLevel",
                },
            ],
            "bodyBatteryValuesArray": [[level, 1735819200000], [None, 1735819200001]],
        }
    ]


def save(store, rows, started=START, finished=END, path="private.json"):
    return store.save_garmin_health(
        rows, fetch_started_at=started, fetched_at=finished, raw_file_path=path
    )


def test_body_battery_uses_descriptors_and_utc_milliseconds():
    rows = parse_body_battery(battery(), DAY)
    sample = rows["garmin_body_battery_samples"][0]
    assert sample == {"day": "2025-01-02", "recorded_at": "2025-01-02T12:00:00+00:00", "level": 42}
    assert rows["garmin_body_battery_days"] == [{"day": "2025-01-02", "charged": 12, "drained": 8}]


def test_body_battery_empty_placeholders_are_unavailable():
    payload = [
        {
            "date": DAY.isoformat(),
            "charged": None,
            "drained": None,
            "bodyBatteryValueDescriptorDTOList": None,
            "bodyBatteryValuesArray": [[1735819200001, None]],
        }
    ]
    assert not any(parse_body_battery(payload, DAY).values())


@pytest.mark.parametrize(
    "field,value",
    [
        ("date", "2025-01-01"),
        ("charged", True),
        ("charged", -1),
        ("bodyBatteryValueDescriptorDTOList", None),
        ("bodyBatteryValuesArray", [[42, True]]),
        ("bodyBatteryValuesArray", [[101, 1735819200000]]),
        ("bodyBatteryValuesArray", [[42, 1735819200000], [43, 1735819200000]]),
    ],
)
def test_body_battery_rejects_malformed_response(field, value):
    payload = battery()
    payload[0][field] = value
    with pytest.raises(ValueError):
        parse_body_battery(payload, DAY)


def test_vo2_preserves_category_report_date_and_precise_value():
    rows = parse_vo2(
        [
            {
                "generic": {
                    "calendarDate": "2025-01-01",
                    "vo2MaxPreciseValue": 48.2,
                    "vo2MaxValue": 48,
                },
                "cycling": {"vo2MaxValue": 51},
            }
        ],
        DAY,
    )
    assert rows["garmin_vo2_daily"] == [
        {"day": "2025-01-01", "category": "generic", "vo2_ml_kg_min": 48.2},
        {"day": "2025-01-02", "category": "cycling", "vo2_ml_kg_min": 51},
    ]


@pytest.mark.parametrize(
    "payload",
    [[], [{"generic": None, "cycling": None}], [{"generic": {"vo2MaxPreciseValue": None}}]],
)
def test_vo2_unavailable(payload):
    assert not any(parse_vo2(payload, DAY).values())


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [{"generic": {"calendarDate": None, "vo2MaxValue": 40}}],
        [{"generic": {"vo2MaxValue": True}}],
        [{"generic": {"vo2MaxValue": -1}}],
        [{"generic": {"vo2MaxValue": float("nan")}}],
    ],
)
def test_vo2_rejects_bad_values(payload):
    with pytest.raises(ValueError):
        parse_vo2(payload, DAY)


def test_upsert_corrections_partial_freshness_and_stale_requests(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    assert save(store, parse_body_battery(battery(), DAY)) == 2
    newer = datetime(2025, 1, 3, 2, tzinfo=UTC)
    partial = battery(35)
    partial[0]["charged"] = 0
    partial[0]["drained"] = None
    assert save(store, parse_body_battery(partial, DAY), newer, newer, "new.json") == 2
    summary = store.list("garmin_body_battery_days")[0]
    assert summary["charged"] == 0 and summary["drained"] == 8
    assert summary["charged_raw_file_path"] == "new.json"
    assert summary["drained_raw_file_path"] == "private.json"
    assert summary["drained_fetched_at"] == END.isoformat().replace("+00:00", "Z")
    assert save(store, parse_body_battery(battery(80), DAY), START, newer) == 0
    assert store.list("garmin_body_battery_samples")[0]["level"] == 35
    assert len(store.list("garmin_body_battery_samples")) == 1
    assert save(store, parse_body_battery([], DAY), newer, newer) == 0
    assert store.list("garmin_body_battery_samples")[0]["level"] == 35


def test_health_transaction_rolls_back_on_database_failure(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    with sqlite3.connect(store.path) as db:
        db.execute(
            "CREATE TRIGGER fail_sample BEFORE INSERT ON garmin_body_battery_samples "
            "BEGIN SELECT RAISE(ABORT, 'sample failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        save(store, parse_body_battery(battery(), DAY))
    assert store.list("garmin_body_battery_days") == []


def test_vo2_stale_order_uses_source_date(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    payload = [{"generic": {"calendarDate": "2025-01-01", "vo2MaxValue": 50}}]
    save(store, parse_vo2(payload, DAY))
    payload[0]["generic"]["vo2MaxValue"] = 45
    older = datetime(2025, 1, 2, tzinfo=UTC)
    assert save(store, parse_vo2(payload, date(2025, 1, 3)), older, END) == 0
    assert store.list("garmin_vo2_daily")[0]["vo2_ml_kg_min"] == 50


def test_health_latest_uses_observation_time_and_keeps_categories(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    save(store, parse_body_battery(battery(), DAY))
    save(store, parse_vo2([{"generic": {"vo2MaxValue": 50}, "cycling": {"vo2MaxValue": 55}}], DAY))
    save(store, parse_vo2([{"generic": {"vo2MaxValue": 45}}], date(2025, 1, 1)))
    latest = store.latest_garmin_health()
    assert latest["body_battery"]["level"] == 42
    assert latest["body_battery"]["fetch_started_at"]
    assert latest["vo2"]["generic"]["vo2_ml_kg_min"] == 50
    assert latest["vo2"]["cycling"]["vo2_ml_kg_min"] == 55


def test_sync_database_failure_removes_only_its_archive(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    archive = tmp_path / "archive"
    archive.mkdir()
    existing = archive / "existing.json"
    existing.write_text("{}")
    with sqlite3.connect(store.path) as db:
        db.execute(
            "CREATE TRIGGER fail_sample BEFORE INSERT ON garmin_body_battery_samples "
            "BEGIN SELECT RAISE(ABORT, 'sample failure'); END"
        )
    result = sync_health(store, Client(), start_date=DAY, end_date=DAY, archive_dir=archive)
    assert not result["synced"]
    assert list(archive.iterdir()) == [existing]
    assert store.list("garmin_body_battery_days") == []


class Client:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    def get_body_battery(self, start, end):
        self.calls.append(("battery", start))
        if self.failure:
            raise self.failure
        return copy.deepcopy(battery())

    def get_max_metrics(self, day):
        self.calls.append(("vo2", day))
        return []


def test_sync_archives_privately_and_reports_unavailable(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    archive = tmp_path / "archive"
    result = sync_health(store, Client(), start_date=DAY, end_date=DAY, archive_dir=archive)
    assert result["synced"] is True
    assert [row["status"] for row in result["results"]] == ["saved", "unavailable"]
    paths = list(archive.glob("*.json"))
    assert len(paths) == 1
    assert stat.S_IMODE(paths[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(archive.stat().st_mode) == 0o700
    assert store.list("garmin_body_battery_samples")[0]["raw_file_path"] == str(paths[0])


def test_sync_connection_failure_continues_but_rate_limit_stops(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    client = Client(GarminConnectConnectionError("timeout"))
    result = sync_health(
        store, client, start_date=DAY, end_date=DAY, archive_dir=tmp_path / "archive"
    )
    assert not result["synced"] and len(client.calls) == 2
    assert result["results"][0]["status"] == "failed"
    client = Client(GarminConnectTooManyRequestsError("429"))
    result = sync_health(
        store, client, start_date=DAY, end_date=DAY, archive_dir=tmp_path / "archive"
    )
    assert not result["synced"] and len(client.calls) == 1
    assert result["stopped"] is True


def test_health_dates_use_explicit_timezone_and_validate():
    now = datetime(2025, 1, 3, 1, tzinfo=UTC)
    assert health_dates(None, None, "America/New_York", now=now) == (date(2025, 1, 1), DAY)
    assert health_dates(DAY, DAY, None, now=now) == (DAY, DAY)
    with pytest.raises(ValueError, match="timezone"):
        health_dates(None, None, None, now=now)
    with pytest.raises(ValueError):
        health_dates(DAY, date(2025, 1, 1), None, now=now)

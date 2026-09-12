"""Read-only Garmin health imports with observation-level provenance."""

import json
import math
import os
import sqlite3
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

from spotter.store import Store

HealthRows = dict[str, list[dict[str, Any]]]


class HealthClient(Protocol):
    def get_body_battery(self, startdate: str, enddate: str) -> Any: ...

    def get_max_metrics(self, day: str) -> Any: ...


def health_dates(
    since: date | None, through: date | None, timezone: str | None, *, now: datetime
) -> tuple[date, date]:
    """Use an explicit calendar timezone whenever the end date is implicit."""
    if through is None:
        if not timezone:
            raise ValueError("Supply --timezone (IANA name) or an explicit --through date")
        try:
            through = now.astimezone(ZoneInfo(timezone)).date()
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown --timezone; use an IANA name") from error
    since = since or through - timedelta(days=1)
    if since > through:
        raise ValueError("--since must be on or before --through")
    return since, through


def _day(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Missing or invalid Garmin calendar date")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Garmin calendar date must use YYYY-MM-DD")
    return value


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"Invalid Garmin {name}")
    return value


def _entries(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ValueError("Expected a list of Garmin health objects")
    return payload


def parse_body_battery(payload: Any, requested_day: date) -> HealthRows:
    """Decode descriptor-indexed millisecond UTC samples; preserve null gaps."""
    rows: HealthRows = {"garmin_body_battery_days": [], "garmin_body_battery_samples": []}
    seen: dict[str, int] = {}
    entries = _entries(payload)
    if len(entries) > 1:
        raise ValueError("Expected at most one Body Battery day")
    for entry in entries:
        day = _day(entry.get("date"))
        if day != requested_day.isoformat():
            raise ValueError("Body Battery date differs from requested day")
        summary: dict[str, Any] = {"day": day}
        for field in ("charged", "drained"):
            if entry.get(field) is not None:
                summary[field] = _integer(entry[field], field)
        if len(summary) > 1:
            rows["garmin_body_battery_days"].append(summary)
        samples = entry.get("bodyBatteryValuesArray")
        if samples is None:
            samples = []
        if not isinstance(samples, list) or any(not isinstance(row, list) for row in samples):
            raise ValueError("Invalid Body Battery samples")
        descriptors = entry.get("bodyBatteryValueDescriptorDTOList")
        if descriptors is None:
            # Garmin emits timestamp/null placeholder pairs without descriptors.
            if all(len(row) == 2 and type(row[0]) is int and row[1] is None for row in samples):
                continue
            raise ValueError("Body Battery samples lack descriptors")
        indexes = {}
        used_indexes = set()
        for descriptor in _entries(descriptors):
            key = descriptor.get("bodyBatteryValueDescriptorKey")
            index = _integer(descriptor.get("bodyBatteryValueDescriptorIndex"), "descriptor index")
            if not isinstance(key, str) or key in indexes or index in used_indexes:
                raise ValueError("Invalid or duplicate Body Battery descriptor")
            indexes[key] = index
            used_indexes.add(index)
        if "timestamp" not in indexes or "bodyBatteryLevel" not in indexes:
            raise ValueError("Body Battery descriptors lack timestamp or level")
        for sample in samples:
            if len(sample) <= max(indexes.values()):
                raise ValueError("Body Battery sample is shorter than descriptors")
            level = sample[indexes["bodyBatteryLevel"]]
            timestamp = _integer(sample[indexes["timestamp"]], "timestamp")
            if level is None:
                continue
            level = _integer(level, "Body Battery level", 5)
            if level > 100:
                raise ValueError("Body Battery level exceeds 100")
            try:
                recorded_at = (
                    datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=timestamp)
                ).isoformat()
            except OverflowError as error:
                raise ValueError("Invalid Body Battery timestamp") from error
            if recorded_at in seen:
                if seen[recorded_at] != level:
                    raise ValueError("Conflicting Body Battery samples at one timestamp")
                continue
            seen[recorded_at] = level
            rows["garmin_body_battery_samples"].append(
                {"day": day, "recorded_at": recorded_at, "level": level}
            )
    return rows


def parse_vo2(payload: Any, requested_day: date) -> HealthRows:
    """Store daily reported estimates, not inferred measurement dates or sports."""
    observations = {}
    for entry in _entries(payload):
        for category in ("generic", "cycling"):
            metrics = entry.get(category)
            if metrics is None:
                continue
            if not isinstance(metrics, dict):
                raise ValueError("Invalid Garmin VO2 category")
            day = (
                _day(metrics["calendarDate"])
                if "calendarDate" in metrics
                else requested_day.isoformat()
            )
            value = metrics.get("vo2MaxPreciseValue")
            if value is None:
                value = metrics.get("vo2MaxValue")
            if value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("Invalid Garmin VO2 estimate")
            key = (day, category)
            if key in observations and observations[key]["vo2_ml_kg_min"] != value:
                raise ValueError("Conflicting Garmin VO2 estimates for one day/category")
            observations[key] = {"day": day, "category": category, "vo2_ml_kg_min": value}
    return {"garmin_vo2_daily": list(observations.values())}


def _archive(directory: Path, payload: Any) -> Path:
    content = json.dumps(payload, allow_nan=False).encode()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    descriptor, name = tempfile.mkstemp(prefix="health-", suffix=".json", dir=directory)
    path = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def sync_health(
    store: Store, client: HealthClient, *, start_date: date, end_date: date, archive_dir: Path
) -> dict[str, Any]:
    """Fetch endpoint/date units sequentially, committing each valid response atomically."""
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    results = []
    day = start_date
    while day <= end_date:
        for endpoint, parse in (("body_battery", parse_body_battery), ("vo2", parse_vo2)):
            result = {"endpoint": endpoint, "day": day.isoformat()}
            path = None
            try:
                started = datetime.now(UTC)
                if endpoint == "body_battery":
                    payload = client.get_body_battery(day.isoformat(), day.isoformat())
                else:
                    payload = client.get_max_metrics(day.isoformat())
                finished = datetime.now(UTC)
                rows = parse(payload, day)
                if not any(rows.values()):
                    results.append(result | {"status": "unavailable"})
                    continue
                path = _archive(archive_dir, payload)
                count = store.save_garmin_health(
                    rows, fetch_started_at=started, fetched_at=finished, raw_file_path=str(path)
                )
                if count == 0:
                    path.unlink(missing_ok=True)
                results.append(
                    result | {"status": "saved" if count else "unchanged", "rows_saved": count}
                )
            except (GarminConnectAuthenticationError, GarminConnectTooManyRequestsError) as error:
                guidance = (
                    "Authentication expired; run garmin-login."
                    if isinstance(error, GarminConnectAuthenticationError)
                    else "Garmin rate limited requests; wait before retrying."
                )
                results.append(result | {"status": "failed", "reason": guidance})
                return {"synced": False, "stopped": True, "results": results}
            except (
                GarminConnectConnectionError,
                GarminConnectNotFoundError,
                ValueError,
                TypeError,
                sqlite3.Error,
                OSError,
            ) as error:
                if path is not None:
                    path.unlink(missing_ok=True)
                results.append(result | {"status": "failed", "reason": str(error)})
        if day == end_date:
            break
        day += timedelta(days=1)
    return {
        "synced": not any(row["status"] == "failed" for row in results),
        "stopped": False,
        "results": results,
    }

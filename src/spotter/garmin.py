import json
import os
import sqlite3
import tempfile
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from spotter.store import GarminActivityAlreadyImported, GarminRunAlreadyClaimed, Store


class GarminClient(Protocol):
    def get_activities_by_date(self, startdate: str, enddate: str) -> list[dict[str, Any]]: ...

    def get_activity_details(self, activity_id: str) -> dict[str, Any]: ...

    def download_original_activity(self, activity_id: str) -> bytes: ...

    def get_stats(self, day: str) -> dict[str, Any]: ...


class GarminCloudClient:
    """Expose the Garmin operations used by Spotter."""

    def __init__(self, client: Garmin) -> None:
        self._client = client

    def get_activities_by_date(self, startdate: str, enddate: str) -> list[dict[str, Any]]:
        """List completed activities in an inclusive date range."""
        return self._client.get_activities_by_date(startdate, enddate)

    def get_activity_details(self, activity_id: str) -> dict[str, Any]:
        """Return Garmin's detailed activity response."""
        return self._client.get_activity_details(activity_id)

    def download_original_activity(self, activity_id: str) -> bytes:
        """Download Garmin's archive containing the original FIT file."""
        return self._client.download_activity(activity_id, Garmin.ActivityDownloadFormat.ORIGINAL)

    def get_stats(self, day: str) -> dict[str, Any]:
        """Return Garmin's daily wellness summary."""
        return self._client.get_stats(day)


def _start_at(activity: Mapping[str, Any]) -> datetime:
    value = activity.get("startTimeGMT")
    if not isinstance(value, str):
        raise ValueError("Garmin activity has no startTimeGMT")
    parsed = datetime.fromisoformat(value.replace(" ", "T"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _activity_type(activity: Mapping[str, Any]) -> str:
    value = activity.get("activityType")
    if not isinstance(value, Mapping) or not isinstance(value.get("typeKey"), str):
        raise ValueError("Garmin activity has no activity type")
    return value["typeKey"]


def _find_compatible_run(
    store: Store, start_at: datetime
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    candidates = []
    for run in store.list("runs"):
        if store.find_one("garmin_activities", "run_id", run["id"]) is not None:
            continue
        if run["workout_id"] is None:
            continue
        session = store.get("sessions", run["workout_id"])
        if session["start_at"] is None:
            continue
        recorded = datetime.fromisoformat(session["start_at"])
        difference = abs((recorded.astimezone(UTC) - start_at.astimezone(UTC)).total_seconds())
        if difference <= 30 * 60:
            candidates.append((difference, session, run))
    if not candidates:
        return None
    _, session, run = min(candidates, key=lambda candidate: candidate[0])
    return session, run


def _is_run(activity_type: str) -> bool:
    return "running" in activity_type or activity_type in {"treadmill", "track_running"}


def _run_values(activity: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    distance = activity.get("distance")
    duration = activity.get("duration")
    if isinstance(distance, int | float):
        values.update(distance=distance / 1000, distance_unit="km")
    if isinstance(duration, int | float) and duration > 0:
        values["duration_seconds"] = duration
    return values


def _number(activity: Mapping[str, Any], field: str) -> float | None:
    value = activity.get(field)
    return float(value) if isinstance(value, int | float) else None


def _validate_activity_id(activity_id: str) -> None:
    if not activity_id.isascii() or not activity_id.isdigit() or int(activity_id) <= 0:
        raise ValueError("Garmin activity ID must be a positive integer")


def _write_private_archive(archive_dir: Path, activity_id: str, content: bytes) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive_dir.chmod(0o700)
    final_path = archive_dir / f"{activity_id}-{uuid4().hex}.zip"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{activity_id}.", dir=archive_dir)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        stream = os.fdopen(descriptor, "wb")
        descriptor = -1
        with stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(final_path)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
        raise
    return final_path


def sync_activities(
    store: Store,
    client: GarminClient,
    *,
    start_date: date,
    end_date: date,
    archive_dir: Path,
) -> dict[str, Any]:
    """Import completed Garmin activities while keeping failed items retryable."""
    try:
        activities = client.get_activities_by_date(start_date.isoformat(), end_date.isoformat())
    except GarminConnectAuthenticationError as error:
        raise ValueError("Garmin authentication failed; run spotter garmin-login again") from error
    except GarminConnectTooManyRequestsError as error:
        raise ValueError("Garmin rate limited activity sync; retry later") from error
    imported = 0
    skipped = 0
    failures: list[dict[str, str]] = []
    archive_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive_dir.chmod(0o700)

    for activity in activities:
        activity_id = str(activity.get("activityId", ""))
        if not activity_id:
            failures.append({"garmin_activity_id": "unknown", "reason": "Missing activityId"})
            continue
        if store.find_one("garmin_activities", "garmin_activity_id", activity_id) is not None:
            skipped += 1
            continue
        try:
            _validate_activity_id(activity_id)
            start_at = _start_at(activity)
            activity_type = _activity_type(activity)
            details = client.get_activity_details(activity_id)
            original = client.download_original_activity(activity_id)
            archive_path = _write_private_archive(archive_dir, activity_id, original)

            session = None
            run = None
            if _is_run(activity_type):
                match = _find_compatible_run(store, start_at)
                if match is not None:
                    session, run = match
            try:
                import_values = {
                    "garmin_activity_id": activity_id,
                    "activity_type": activity_type,
                    "activity_name": activity.get("activityName"),
                    "start_at": start_at.isoformat(),
                    "average_heart_rate": _number(activity, "averageHR"),
                    "max_heart_rate": _number(activity, "maxHR"),
                    "calories": _number(activity, "calories"),
                    "imported_at": datetime.now(UTC).isoformat(),
                    "raw_file_path": str(archive_path),
                    "details_json": json.dumps(details, separators=(",", ":")),
                }
                try:
                    store.save_garmin_activity(
                        session_id=None if session is None else session["id"],
                        session_values={"start_at": start_at.isoformat()},
                        run_id=None if run is None else run["id"],
                        run_values=_run_values(activity) if _is_run(activity_type) else None,
                        garmin_values=import_values,
                    )
                except GarminRunAlreadyClaimed:
                    store.save_garmin_activity(
                        session_id=None,
                        session_values={"start_at": start_at.isoformat()},
                        run_id=None,
                        run_values=_run_values(activity),
                        garmin_values=import_values,
                    )
            except GarminActivityAlreadyImported:
                archive_path.unlink(missing_ok=True)
                skipped += 1
                continue
            except (KeyError, sqlite3.Error, TypeError, ValueError):
                archive_path.unlink(missing_ok=True)
                raise
            imported += 1
        except GarminConnectAuthenticationError as error:
            raise ValueError(
                f"Garmin activity {activity_id} authentication failed; "
                "run spotter garmin-login again"
            ) from error
        except GarminConnectTooManyRequestsError as error:
            raise ValueError(
                f"Garmin activity {activity_id} was rate limited; retry later"
            ) from error
        except (
            GarminConnectConnectionError,
            KeyError,
            OSError,
            sqlite3.Error,
            TypeError,
            ValueError,
        ) as error:
            failures.append({"garmin_activity_id": activity_id, "reason": str(error)})

    return {"imported": imported, "skipped": skipped, "failures": failures}


def sync_daily_steps(
    store: Store,
    client: GarminClient,
    *,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Create or refresh one Garmin step-total record per calendar date."""
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    created = 0
    updated = 0
    failures: list[dict[str, str]] = []
    day = start_date
    while day <= end_date:
        day_text = day.isoformat()
        try:
            stats = client.get_stats(day_text)
            if stats.get("calendarDate") != day_text:
                raise ValueError("Garmin returned a different calendar date")
            total_steps = stats.get("totalSteps")
            if not isinstance(total_steps, int) or isinstance(total_steps, bool):
                raise ValueError("Garmin returned no daily step total")
            values = {
                "day": day_text,
                "total_steps": total_steps,
                "step_goal": stats.get("stepGoal"),
                "synced_at": datetime.now(UTC).isoformat(),
            }
            existing = store.find_one("garmin_daily_steps", "day", day_text)
            if existing is None:
                store.add("garmin_daily_steps", values)
                created += 1
            else:
                store.update("garmin_daily_steps", existing["id"], values)
                updated += 1
        except GarminConnectAuthenticationError as error:
            raise ValueError(
                f"Garmin daily steps for {day_text} authentication failed; "
                "run spotter garmin-login again"
            ) from error
        except GarminConnectTooManyRequestsError as error:
            raise ValueError(
                f"Garmin daily steps for {day_text} were rate limited; retry later"
            ) from error
        except (
            GarminConnectConnectionError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            failures.append({"day": day_text, "reason": str(error)})
        day += timedelta(days=1)
    return {"created": created, "updated": updated, "failures": failures}

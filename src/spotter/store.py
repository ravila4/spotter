from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spotter.models import MODELS, Record


class GarminActivityAlreadyImported(sqlite3.IntegrityError):
    """The Garmin activity was claimed by another import."""


class GarminRunAlreadyClaimed(sqlite3.IntegrityError):
    """The Spotter run was claimed by another Garmin activity."""


class Store:
    """Persist validated workout records using short, atomic transactions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        with closing(self._connect()) as connection, connection:
            for table, model in MODELS.items():
                columns = ["id INTEGER PRIMARY KEY"]
                for name in model.model_fields:
                    sql_type = "TEXT"
                    if name in {
                        "workout_id",
                        "exercise_id",
                        "run_id",
                        "set_order",
                        "reps",
                        "total_steps",
                        "step_goal",
                        "charged",
                        "drained",
                        "level",
                    }:
                        sql_type = "INTEGER"
                    elif name in {
                        "weight",
                        "distance",
                        "duration_seconds",
                        "reported_pace",
                        "max_speed",
                        "average_heart_rate",
                        "max_heart_rate",
                        "calories",
                        "vo2_ml_kg_min",
                    }:
                        sql_type = "REAL"
                    column = f"{name} {sql_type}"
                    if name == "workout_id":
                        column += " REFERENCES sessions(id)"
                    elif name == "exercise_id":
                        column += " REFERENCES exercises(id)"
                    elif name == "run_id":
                        column += " REFERENCES runs(id)"
                    columns.append(column)
                if table == "strength_sets":
                    columns.append("UNIQUE(workout_id, exercise_id, set_order)")
                elif table == "garmin_activities":
                    columns.append("UNIQUE(garmin_activity_id)")
                elif table == "garmin_daily_steps":
                    columns.append("UNIQUE(day)")
                elif table == "garmin_body_battery_days":
                    columns.append("UNIQUE(day)")
                elif table == "garmin_body_battery_samples":
                    columns.append("UNIQUE(recorded_at)")
                elif table == "garmin_vo2_daily":
                    columns.append("UNIQUE(day, category)")
                connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(columns)})")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS garmin_activities_run_id_unique "
                "ON garmin_activities(run_id) WHERE run_id IS NOT NULL"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _model(table: str) -> type[Record]:
        if table not in MODELS:
            raise ValueError(f"Unknown table: {table}; choose from {', '.join(MODELS)}")
        return MODELS[table]

    @staticmethod
    def _present(table: str, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        if table == "runs":
            pace = speed = None
            if result["distance"] and result["duration_seconds"]:
                km = (
                    result["distance"]
                    * {"m": 0.001, "km": 1, "mi": 1.609344}[result["distance_unit"]]
                )
                pace = result["duration_seconds"] / km
                speed = km * 3600 / result["duration_seconds"]
            result["average_pace_seconds_per_km"] = pace
            result["average_speed_kmh"] = speed
        return result

    def add(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        """Return the saved record only after its transaction commits."""
        values = self._model(table).model_validate(data).model_dump(mode="json")
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    f"INSERT INTO {table} ({', '.join(values)}) "
                    f"VALUES ({', '.join('?' for _ in values)})",
                    tuple(values.values()),
                )
                row = connection.execute(
                    f"SELECT * FROM {table} WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
        return self._present(table, row)

    def get(self, table: str, record_id: int) -> dict[str, Any]:
        """Read one record by its stable identifier."""
        self._model(table)
        with closing(self._connect()) as connection:
            row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(f"No {table} record with id {record_id}")
        return self._present(table, row)

    def update(self, table: str, record_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        """Merge a correction atomically; explicit null clears a field."""
        model = self._model(table)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    f"SELECT * FROM {table} WHERE id = ?", (record_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"No {table} record with id {record_id}")
                current = dict(row)
                del current["id"]
                values = model.model_validate(current | changes).model_dump(mode="json")
                connection.execute(
                    f"UPDATE {table} SET {', '.join(f'{key} = ?' for key in values)} WHERE id = ?",
                    (*values.values(), record_id),
                )
                saved = connection.execute(
                    f"SELECT * FROM {table} WHERE id = ?", (record_id,)
                ).fetchone()
        return self._present(table, saved)

    def list(self, table: str, *, workout_id: int | None = None) -> list[dict[str, Any]]:
        """Read records in insertion order, optionally restricted to one workout."""
        model = self._model(table)
        query = f"SELECT * FROM {table}"
        parameters: tuple[int, ...] = ()
        if workout_id is not None:
            if "workout_id" not in model.model_fields:
                raise ValueError(f"{table} has no workout reference")
            query += " WHERE workout_id = ?"
            parameters = (workout_id,)
        with closing(self._connect()) as connection:
            rows = connection.execute(query + " ORDER BY id", parameters).fetchall()
        return [self._present(table, row) for row in rows]

    def find_one(self, table: str, field: str, value: Any) -> dict[str, Any] | None:
        """Find a record by a validated model field."""
        model = self._model(table)
        if field not in model.model_fields:
            raise ValueError(f"{table} has no field named {field}")
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE {field} = ? ORDER BY id LIMIT 1", (value,)
            ).fetchone()
        return None if row is None else self._present(table, row)

    def save_garmin_health(
        self,
        rows: dict[str, list[dict[str, Any]]],
        *,
        fetch_started_at: datetime,
        fetched_at: datetime,
        raw_file_path: str,
    ) -> int:
        """Atomically merge observations; missing values never refresh older facts."""
        if fetch_started_at.utcoffset() is None or fetched_at.utcoffset() is None:
            raise ValueError("Health request times must have timezone offsets")
        if fetched_at < fetch_started_at:
            raise ValueError("Health retrieval finished before it started")
        metadata = {
            "fetch_started_at": fetch_started_at.astimezone(UTC),
            "fetched_at": fetched_at.astimezone(UTC),
            "raw_file_path": raw_file_path,
        }
        keys = {
            "garmin_body_battery_days": ("day",),
            "garmin_body_battery_samples": ("recorded_at",),
            "garmin_vo2_daily": ("day", "category"),
        }
        prepared = []
        for table, observations in rows.items():
            if table not in keys:
                raise ValueError(f"Not a Garmin health table: {table}")
            for observation in observations:
                supplied = dict(observation)
                if table == "garmin_body_battery_days":
                    for field in ("charged", "drained"):
                        if supplied.get(field) is not None:
                            supplied.update(
                                {f"{field}_{key}": value for key, value in metadata.items()}
                            )
                else:
                    supplied.update(metadata)
                values = (
                    self._model(table)
                    .model_validate(supplied)
                    .model_dump(mode="json", exclude_none=True)
                )
                prepared.append((table, values))
        saved = 0
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            for table, values in prepared:
                identity = keys[table]
                where = " AND ".join(f"{key} = ?" for key in identity)
                current = connection.execute(
                    f"SELECT * FROM {table} WHERE {where}", tuple(values[key] for key in identity)
                ).fetchone()
                if current is not None:
                    prefixes = (
                        ("charged_", "drained_") if table == "garmin_body_battery_days" else ("",)
                    )
                    for prefix in prefixes:
                        clock = f"{prefix}fetch_started_at"
                        if clock not in values or current[clock] is None:
                            continue
                        if datetime.fromisoformat(current[clock]) >= fetch_started_at:
                            if not prefix:
                                values = {key: values[key] for key in identity}
                            else:
                                field = prefix.removesuffix("_")
                                values = {
                                    key: value
                                    for key, value in values.items()
                                    if key != field and not key.startswith(prefix)
                                }
                    changes = {key: value for key, value in values.items() if key not in identity}
                    if not changes:
                        continue
                    assignments = ", ".join(f"{key} = ?" for key in changes)
                    connection.execute(
                        f"UPDATE {table} SET {assignments} WHERE id = ?",
                        (*changes.values(), current["id"]),
                    )
                else:
                    if set(values) <= set(identity):
                        continue
                    connection.execute(
                        f"INSERT INTO {table} ({', '.join(values)}) "
                        f"VALUES ({', '.join('?' for _ in values)})",
                        tuple(values.values()),
                    )
                saved += 1
        return saved

    def latest_garmin_health(self) -> dict[str, Any]:
        """Return the newest stored observations, including their provenance and dates."""
        with closing(self._connect()) as connection:
            sample = connection.execute(
                "SELECT * FROM garmin_body_battery_samples ORDER BY recorded_at DESC LIMIT 1"
            ).fetchone()
            summary = connection.execute(
                "SELECT * FROM garmin_body_battery_days ORDER BY day DESC LIMIT 1"
            ).fetchone()
            vo2 = {}
            for category in ("generic", "cycling"):
                row = connection.execute(
                    "SELECT * FROM garmin_vo2_daily WHERE category = ? ORDER BY day DESC LIMIT 1",
                    (category,),
                ).fetchone()
                vo2[category] = dict(row) if row is not None else None
        return {
            "body_battery": dict(sample) if sample is not None else None,
            "body_battery_day": dict(summary) if summary is not None else None,
            "vo2": vo2,
        }

    def save_garmin_activity(
        self,
        *,
        session_id: int | None,
        session_values: dict[str, Any],
        run_id: int | None,
        run_values: dict[str, Any] | None,
        garmin_values: dict[str, Any],
    ) -> dict[str, Any]:
        """Save a Garmin import and its workout records in one transaction."""
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                garmin_activity_id = garmin_values.get("garmin_activity_id")
                if (
                    connection.execute(
                        "SELECT id FROM garmin_activities WHERE garmin_activity_id = ?",
                        (garmin_activity_id,),
                    ).fetchone()
                    is not None
                ):
                    raise GarminActivityAlreadyImported(str(garmin_activity_id))
                if (
                    run_id is not None
                    and connection.execute(
                        "SELECT id FROM garmin_activities WHERE run_id = ?", (run_id,)
                    ).fetchone()
                    is not None
                ):
                    raise GarminRunAlreadyClaimed(str(run_id))
                if session_id is None:
                    values = (
                        MODELS["sessions"].model_validate(session_values).model_dump(mode="json")
                    )
                    cursor = connection.execute(
                        f"INSERT INTO sessions ({', '.join(values)}) "
                        f"VALUES ({', '.join('?' for _ in values)})",
                        tuple(values.values()),
                    )
                    session_id = cursor.lastrowid
                elif (
                    connection.execute(
                        "SELECT id FROM sessions WHERE id = ?", (session_id,)
                    ).fetchone()
                    is None
                ):
                    raise KeyError(f"No sessions record with id {session_id}")

                if run_values is not None:
                    supplied = run_values | {"workout_id": session_id}
                    if run_id is None:
                        values = MODELS["runs"].model_validate(supplied).model_dump(mode="json")
                        cursor = connection.execute(
                            f"INSERT INTO runs ({', '.join(values)}) "
                            f"VALUES ({', '.join('?' for _ in values)})",
                            tuple(values.values()),
                        )
                        run_id = cursor.lastrowid
                    else:
                        row = connection.execute(
                            "SELECT * FROM runs WHERE id = ?", (run_id,)
                        ).fetchone()
                        if row is None:
                            raise KeyError(f"No runs record with id {run_id}")
                        current = dict(row)
                        del current["id"]
                        values = (
                            MODELS["runs"]
                            .model_validate(current | supplied)
                            .model_dump(mode="json")
                        )
                        assignments = ", ".join(f"{key} = ?" for key in values)
                        connection.execute(
                            f"UPDATE runs SET {assignments} WHERE id = ?",
                            (*values.values(), run_id),
                        )

                supplied_garmin = garmin_values | {"workout_id": session_id, "run_id": run_id}
                values = (
                    MODELS["garmin_activities"]
                    .model_validate(supplied_garmin)
                    .model_dump(mode="json")
                )
                cursor = connection.execute(
                    f"INSERT INTO garmin_activities ({', '.join(values)}) "
                    f"VALUES ({', '.join('?' for _ in values)})",
                    tuple(values.values()),
                )
                saved = connection.execute(
                    "SELECT * FROM garmin_activities WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
        return self._present("garmin_activities", saved)

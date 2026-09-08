import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from spotter.models import MODELS, Record


class Store:
    """Persist validated workout records using short, atomic transactions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        with closing(self._connect()) as connection, connection:
            for table, model in MODELS.items():
                columns = ["id INTEGER PRIMARY KEY"]
                for name in model.model_fields:
                    sql_type = "TEXT"
                    if name in {"workout_id", "exercise_id", "set_order", "reps"}:
                        sql_type = "INTEGER"
                    elif name in {
                        "weight",
                        "distance",
                        "duration_seconds",
                        "reported_pace",
                        "max_speed",
                    }:
                        sql_type = "REAL"
                    column = f"{name} {sql_type}"
                    if name == "workout_id":
                        column += " REFERENCES sessions(id)"
                    elif name == "exercise_id":
                        column += " REFERENCES exercises(id)"
                    columns.append(column)
                if table == "strength_sets":
                    columns.append("UNIQUE(workout_id, exercise_id, set_order)")
                connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(columns)})")

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

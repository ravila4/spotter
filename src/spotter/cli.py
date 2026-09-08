import argparse
import json
import sqlite3
import sys
from typing import Any

from spotter.models import MODELS
from spotter.store import Store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read and save workout records as JSON.")
    parser.add_argument("--db", default="spotter.sqlite3", help="SQLite database path")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create the database tables")
    commands.add_parser("schema", help="Show accepted record fields and units")
    for name in ("add", "update", "get", "list"):
        command = commands.add_parser(name)
        command.add_argument("table", choices=MODELS)
        if name in {"update", "get"}:
            command.add_argument("record_id", type=int)
        if name in {"add", "update"}:
            command.add_argument("data", help="JSON object containing record fields")
        if name == "list":
            command.add_argument("--workout-id", type=int)
    return parser


def _execute(args: argparse.Namespace) -> Any:
    if args.command == "schema":
        return {name: model.model_json_schema() for name, model in MODELS.items()}
    store = Store(args.db)
    match args.command:
        case "init":
            return {"initialized": True, "database": str(store.path)}
        case "add":
            record = store.add(args.table, json.loads(args.data))
            return {"saved": True, "record": record}
        case "update":
            record = store.update(args.table, args.record_id, json.loads(args.data))
            return {"saved": True, "record": record}
        case "get":
            return store.get(args.table, args.record_id)
        case "list":
            return store.list(args.table, workout_id=args.workout_id)


def main(argv: list[str] | None = None) -> int:
    """Keep failed writes out of the success stream consumed by agents."""
    args = _parser().parse_args(argv)
    try:
        result = _execute(args)
    except (ValueError, TypeError, KeyError, sqlite3.Error, OSError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

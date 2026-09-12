import argparse
import getpass
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

from spotter.garmin import GarminCloudClient, sync_activities, sync_daily_steps
from spotter.models import MODELS
from spotter.store import Store

GARMIN_DIR = Path.home() / ".local" / "share" / "spotter" / "garmin"
GARMIN_TOKENS = Path.home() / ".config" / "spotter" / "garmin"


def _garmin_sync_dates(
    since: date | None, through: date | None, *, today: date
) -> tuple[date, date, date]:
    end_date = through or today
    activity_start = since or end_date - timedelta(days=7)
    step_start = since or end_date
    if activity_start > end_date:
        raise ValueError("--since must be on or before --through")
    return activity_start, step_start, end_date


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read and save workout records as JSON.")
    parser.add_argument("--db", default="spotter.sqlite3", help="SQLite database path")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create the database tables")
    commands.add_parser("schema", help="Show accepted record fields and units")
    login = commands.add_parser("garmin-login", help="Authenticate with Garmin Connect")
    login.add_argument("--email", help="Garmin Connect email; prompts when omitted")
    sync = commands.add_parser("garmin-sync", help="Import completed Garmin activities")
    sync.add_argument("--since", type=date.fromisoformat, help="First activity date (YYYY-MM-DD)")
    sync.add_argument("--through", type=date.fromisoformat, help="Last activity date (YYYY-MM-DD)")
    sync.add_argument(
        "--garmin-dir", type=Path, default=GARMIN_DIR, help="Private Garmin data path"
    )
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
    if args.command == "garmin-login":
        GARMIN_TOKENS.mkdir(parents=True, exist_ok=True, mode=0o700)
        email = args.email or input("Garmin Connect email: ")
        password = getpass.getpass("Garmin Connect password: ")
        client = Garmin(email, password, prompt_mfa=lambda: input("Garmin MFA code: "))
        client.login(str(GARMIN_TOKENS))
        return {"authenticated": True, "token_store": str(GARMIN_TOKENS)}
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
        case "garmin-sync":
            activity_since, step_since, through = _garmin_sync_dates(
                args.since, args.through, today=date.today()
            )
            client = Garmin()
            client.login(str(GARMIN_TOKENS))
            cloud = GarminCloudClient(client)
            activities = sync_activities(
                store,
                cloud,
                start_date=activity_since,
                end_date=through,
                archive_dir=args.garmin_dir / "activities",
            )
            daily_steps = sync_daily_steps(
                store,
                cloud,
                start_date=step_since,
                end_date=through,
            )
            return {
                "synced": not activities["failures"] and not daily_steps["failures"],
                "activities": activities,
                "daily_steps": daily_steps,
            }


def main(argv: list[str] | None = None) -> int:
    """Keep failed writes out of the success stream consumed by agents."""
    args = _parser().parse_args(argv)
    try:
        result = _execute(args)
    except (
        ValueError,
        TypeError,
        KeyError,
        sqlite3.Error,
        OSError,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectNotFoundError,
        GarminConnectTooManyRequestsError,
    ) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    if isinstance(result, dict) and result.get("synced") is False:
        print(json.dumps(result), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

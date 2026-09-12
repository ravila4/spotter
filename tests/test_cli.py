import json
import stat
import subprocess
import sys
from datetime import date
from types import SimpleNamespace

import spotter.cli


def invoke(path, *args):
    return subprocess.run(
        [sys.executable, "-m", "spotter.cli", "--db", str(path), *args],
        capture_output=True,
        text=True,
    )


def test_agent_can_save_correct_and_read(tmp_path):
    path = tmp_path / "spotter.sqlite3"
    added = invoke(path, "add", "sessions", '{"notes":"Lunch workout"}')
    assert added.returncode == 0, added.stderr
    record = json.loads(added.stdout)["record"]
    updated = invoke(path, "update", "sessions", str(record["id"]), '{"notes":"Evening workout"}')
    assert json.loads(updated.stdout)["saved"] is True
    listed = invoke(path, "list", "sessions")
    assert json.loads(listed.stdout)[0]["notes"] == "Evening workout"
    fetched = invoke(path, "get", "sessions", str(record["id"]))
    assert json.loads(fetched.stdout)["id"] == record["id"]


def test_cli_failure_does_not_claim_saved(tmp_path):
    result = invoke(tmp_path / "spotter.sqlite3", "add", "runs", '{"distance":5}')
    assert result.returncode != 0
    assert result.stdout == ""
    assert "distance_unit" in result.stderr


def test_cli_invalid_json(tmp_path):
    result = invoke(tmp_path / "spotter.sqlite3", "add", "runs", "{")
    assert result.returncode != 0
    assert result.stdout == ""


def test_cli_schema(tmp_path):
    result = invoke(tmp_path / "spotter.sqlite3", "schema")
    assert "reported_pace" in json.loads(result.stdout)["runs"]["properties"]


def test_cli_workout_filter(tmp_path):
    path = tmp_path / "spotter.sqlite3"
    invoke(path, "add", "sessions", "{}")
    invoke(path, "add", "sessions", "{}")
    invoke(path, "add", "runs", '{"workout_id":1}')
    result = invoke(path, "list", "runs", "--workout-id", "2")
    assert json.loads(result.stdout) == []


def test_cli_init(tmp_path):
    path = tmp_path / "spotter.sqlite3"
    result = invoke(path, "init")
    assert result.returncode == 0
    assert path.exists()


def test_partial_garmin_sync_exits_nonzero_without_claiming_success(monkeypatch, capsys):
    result = {
        "synced": False,
        "imported": 0,
        "skipped": 0,
        "failures": [{"garmin_activity_id": "12345", "reason": "Garmin timed out"}],
    }
    monkeypatch.setattr(spotter.cli, "_execute", lambda args: result)

    status = spotter.cli.main(["garmin-sync"])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert json.loads(captured.err) == result


def test_default_garmin_sync_backfills_activities_but_only_today_steps():
    assert spotter.cli._garmin_sync_dates(None, None, today=date(2026, 9, 11)) == (
        date(2026, 9, 4),
        date(2026, 9, 11),
        date(2026, 9, 11),
    )


def test_garmin_login_repairs_token_directory_permissions(tmp_path, monkeypatch):
    token_dir = tmp_path / "tokens"
    token_dir.mkdir(mode=0o755)

    class FakeLogin:
        def __init__(self, email, password, prompt_mfa):
            pass

        def login(self, path):
            assert path == str(token_dir)

    monkeypatch.setattr(spotter.cli, "GARMIN_TOKENS", token_dir)
    monkeypatch.setattr(spotter.cli, "Garmin", FakeLogin)
    monkeypatch.setattr(spotter.cli.getpass, "getpass", lambda prompt: "secret")

    spotter.cli._execute(SimpleNamespace(command="garmin-login", email="user@example.com"))

    assert stat.S_IMODE(token_dir.stat().st_mode) == 0o700


def test_health_sync_requires_date_context_before_login(tmp_path, monkeypatch, capsys):
    def unexpected_login():
        raise AssertionError("Login must not happen before date validation")

    monkeypatch.setattr(spotter.cli, "Garmin", unexpected_login)
    status = spotter.cli.main(["--db", str(tmp_path / "test.sqlite3"), "garmin-health-sync"])
    assert status == 1
    assert "timezone" in capsys.readouterr().err


def test_health_sync_cli_persists_response(tmp_path, monkeypatch, capsys):
    class HealthClient:
        def login(self, path):
            pass

        def get_body_battery(self, start, end):
            assert start == end == "2025-01-02"
            return []

        def get_max_metrics(self, day):
            return [{"generic": {"calendarDate": day, "vo2MaxPreciseValue": 48.2}}]

    monkeypatch.setattr(spotter.cli, "Garmin", HealthClient)
    path = tmp_path / "test.sqlite3"
    status = spotter.cli.main(
        [
            "--db",
            str(path),
            "garmin-health-sync",
            "--since",
            "2025-01-02",
            "--through",
            "2025-01-02",
            "--garmin-dir",
            str(tmp_path / "private"),
        ]
    )
    assert status == 0
    assert json.loads(capsys.readouterr().out)["synced"] is True
    rows = spotter.cli.Store(path).list("garmin_vo2_daily")
    assert rows[0]["vo2_ml_kg_min"] == 48.2

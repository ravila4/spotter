import json
import subprocess
import sys


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

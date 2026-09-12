# Spotter

Spotter stores workout history in a local SQLite database. An agent handles the
conversation and calls a small command interface to save and retrieve records.
The phone connection comes from your existing agent setup.

Run from this directory:

```sh
uv sync
uv run spotter init
uv run spotter schema
```

Have your agent read [AGENTS.md](AGENTS.md) for logging and coaching instructions.
The default database is `spotter.sqlite3`; select another file with
`uv run spotter --db /absolute/path/workouts.sqlite3 ...`.

## Record a workout

These commands are for the agent. You describe the workout in ordinary language.
Use the IDs returned by each command in subsequent commands; the IDs below are
examples for an empty database.

```sh
uv run spotter add sessions '{"start_at":"2026-09-08T12:00:00-04:00"}'
uv run spotter add exercises '{"name":"Leg press","equipment":"Seated machine"}'
uv run spotter add strength_sets '{"workout_id":1,"exercise_id":1,"set_order":1,"reps":8,"weight":80,"weight_unit":"kg","effort_note":"Last rep was hard"}'
uv run spotter update strength_sets 1 '{"reps":9}'
uv run spotter list strength_sets --workout-id 1
uv run spotter add runs '{"workout_id":1,"distance":5,"distance_unit":"km","duration_seconds":1800,"duration_kind":"elapsed"}'
```

Writes return `saved: true` and the committed record. Failures return a nonzero
exit code and an error on standard error. Corrections change the existing record;
omitted fields stay unchanged and explicit null clears a field. Repeating an add
creates another record, so inspect history before retrying an interrupted request.

## Data

Every table has an integer ID and optional notes. Fields may be left unknown.
Numeric values require explicit units when applicable. Supplied timestamps must
include a timezone offset. The Python models define the schema and validation;
`spotter schema` exposes the fields as JSON Schema.

| Table | Fields besides ID and notes |
| --- | --- |
| Body measurements | Measurement time, weight, weight unit |
| Sessions | Start time, end time |
| Runs | Workout ID, distance and unit, duration in seconds, moving/elapsed duration kind, reported pace and unit/kind, maximum speed and unit |
| Exercises | Name, equipment description |
| Strength sets | Workout ID, exercise ID, set order, reps, weight and unit, effort note |
| Garmin activities | Garmin activity ID, linked workout/run, activity type, heart rate, calories, import metadata, raw details |
| Garmin daily steps | Calendar date, total steps, optional step goal, last sync time |

Each set order is unique within a workout and exercise when all three values are
known. Foreign keys reject references to nonexistent workouts or exercises.
Set weight can be zero; unknown weight is null. Effort stays as free text.

Run responses include calculated average speed in km/h and pace in seconds/km.
Reported pace remains separate and identifies current, average, or unknown pace.
No average pace is returned when distance or duration is missing or distance is
zero. Distance units are m, km, or mi; weights use kg or lb. Reported pace uses
sec/km or sec/mi, and maximum speed uses km/h or mph.

The initial version has no dashboard or natural-language parser. Your agent
interprets speech, text, and photos; these tools handle storage. The database is
gitignored. Back it up separately if you want to retain history.

## Garmin Connect sync

Authenticate once from an interactive terminal:

```sh
uv run spotter garmin-login
```

The command prompts for the Garmin Connect email, password, and MFA code when
required. It stores reusable login tokens under
`~/.config/spotter/garmin/`; it does not store the password. Garmin may require
another login after a password or security change, token invalidation, or an
upstream authentication change.

Import activities from the last seven days:

```sh
uv run spotter garmin-sync
```

Choose an explicit range when backfilling older activities:

```sh
uv run spotter garmin-sync --since 2026-09-01 --through 2026-09-11
```

The sync runs after the watch uploads a completed activity to Garmin Connect.
It downloads Garmin's original FIT archive to
`~/.local/share/spotter/garmin/activities/`, preserves the detailed activity
response, and records average and maximum heart rate. Running activities create
or enrich a Spotter run. A session beginning within 30 minutes is treated as the
same workout. Garmin activity IDs prevent duplicate imports. The command also
creates or refreshes one daily step-total record per date, including the current
day's growing total.

Successful syncs return `synced: true`. A partial failure returns a nonzero exit
code and identifies each activity that can be retried. This integration uses
Garmin Connect's private interface through `python-garminconnect`; Garmin changes
may occasionally require a dependency update or another login.

## Development

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

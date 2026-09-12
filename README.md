# Spotter

Spotter is a small, local workout log for Codex.

Run Spotter on a desktop or home server and connect to that Codex session from
your phone. Tell Codex what you did in ordinary language, and it saves the workout
as you go. For example:

> Leg press, 80 kg, 8 reps. The last rep was hard.

Spotter can also read completed activities, steps, Body Battery, and VO2 max
reports from Garmin Connect. Your workout and health database stays on the
computer running Spotter.

## Setup

Spotter requires Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run spotter init
```

Have Codex read [AGENTS.md](AGENTS.md). It explains how to record workouts and
use the saved history while coaching.

## Garmin Connect

Sign in once from an interactive terminal:

```sh
uv run spotter garmin-login
```

The login tokens are stored outside the repository. Your password is not saved.
You may need to sign in again if Garmin expires the tokens.

Import recent activities and daily steps:

```sh
uv run spotter garmin-sync
```

Import Body Battery and VO2 max reports for today and yesterday:

```sh
uv run spotter garmin-health-sync --timezone America/New_York
uv run spotter garmin-health-latest
```

Use your own IANA timezone in place of `America/New_York`. Both sync commands
accept `--since YYYY-MM-DD --through YYYY-MM-DD` to import an older date range.

Garmin access is read-only. Spotter uses Garmin Connect's private interface, so
Garmin changes may occasionally break the sync. More detail is available in the
[health data design](docs/garmin-health-plan.md).

## Data and privacy

Spotter stores its records in `spotter.sqlite3` by default. Database files are
gitignored. Garmin tokens and downloaded source data are also stored outside the
repository. Back up these files separately if you want to keep your history.

Use another database with `--db`:

```sh
uv run spotter --db /path/to/workouts.sqlite3 list sessions
```

Run `uv run spotter schema` to see the available records and fields.

## Development

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## License

Spotter is available under the [MIT License](LICENSE).

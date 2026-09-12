# Garmin health data design

Read-only health sync adds Body Battery and daily reported VO2 estimates alongside
workouts, manual measurements, activities, and steps.

```text
Garmin Connect
  |-- daily Body Battery response
  |     |-- garmin_body_battery_days
  |     `-- garmin_body_battery_samples
  `-- max-metrics response
        `-- garmin_vo2_daily
```

| Table | Identity | Stored facts |
| --- | --- | --- |
| garmin_body_battery_days | Garmin calendar date | Charged/drained totals with separate request times and archive paths |
| garmin_body_battery_samples | UTC timestamp | Garmin calendar date, level, request times and archive path |
| garmin_vo2_daily | Report date and category | Generic/cycling VO2 in ml/kg/min, request times and archive path |

## Payload contracts

Body Battery responses use descriptor-indexed arrays. Timestamp values are
milliseconds since the UTC epoch; levels range from 5 to 100. Null levels mark
gaps. Empty days can contain timestamp/null placeholder pairs without descriptors.
Unknown non-null values fail validation rather than being interpreted as sentinels.
The source date must match the requested day. Duplicate timestamps with conflicting
levels fail validation; identical samples are deduplicated. A timestamp identifies
one reading even if adjacent daily responses overlap.

Max-metrics responses are lists with optional `generic` and `cycling` objects.
`vo2MaxPreciseValue` takes precedence over `vo2MaxValue`. A valid source
`calendarDate` is retained; when that key is absent, the requested day identifies
the daily report. A present malformed date fails validation. These dates do not
establish when a new estimate was measured. Generic is preserved without assuming
that every value came from running.

The Body Battery contract was checked against a populated response. The VO2
structure is supported by the upstream
[garmin-grafana importer](https://github.com/arpanghosh8453/garmin-grafana/blob/main/src/garmin_grafana/garmin_fetch.py)
and synthetic tests; the connected account returned an empty list during initial
verification. Populated account VO2 data remains to be checked when available.
The [python-garminconnect API](https://github.com/cyberjunky/python-garminconnect)
passes these private Garmin responses through, so schema changes can require
parser updates.

## Persistence and freshness

Validate a complete endpoint response before opening a write transaction. Save its
rows atomically. Malformed data, storage errors, and network failures preserve
previous observations. Values are not monotonic: later requests may lower them.

`fetch_started_at` orders overlapping requests inside the SQLite write transaction;
`fetched_at` records retrieval completion. This orders local requests, not Garmin
revisions, and assumes a stable host clock. Each sample and VO2 report carries both
timestamps. Charged and drained have separate timestamps and archive paths so a
partial daily summary cannot refresh the age or provenance of an omitted field.

Empty responses, omitted samples, and null values preserve existing observations
without refreshing them. Omission does not prove deletion. Latest queries return
the source date/time and retrieval times. History listings use insertion order;
analysis must order by observation/report time.

Raw responses use unique private filenames, referenced by saved rows. Failed or
stale writes remove only their own unused archive. Older source files remain on
disk after corrections. A process crash before commit can leave an unreferenced
private archive; it cannot partially commit the endpoint's rows.

## Sync behavior

`garmin-health-sync` runs separately from activity/step sync and reuses its login.
Without `--through`, an explicit IANA `--timezone` selects today's date. Without
`--since`, the window begins one day before the end date. Explicit inclusive ranges
support backfills; the default two days do not guarantee capture of older uploads.

Requests run sequentially. Each endpoint/date reports saved, unchanged, unavailable,
or failed. Authentication failures and rate limits stop remaining requests.
Recoverable failures leave independent endpoints retryable. Any failed endpoint
causes a nonzero command exit, including when other endpoints were saved.

This design adds no Garmin writes, scheduler, dashboard, generic metric table,
provider framework, or live sensor streaming. Sleep and HRV need separate designs.

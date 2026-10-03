# Using the evidence with Spotter

This page maps the knowledge collection to the current CLI schema. It describes
possible uses; the wiki does not add calculations or change coaching behavior.

| Question | Available records | What still needs checking |
| --- | --- | --- |
| How has this lift progressed? | Exercise, equipment, sets, reps, load, free-text effort | Comparable equipment and units; incomplete sets; training goal |
| How much have I run? | Distance, duration, moving/elapsed distinction | Missing sessions and consistent duration definitions |
| How active have I been? | Daily steps, recorded sessions | Steps alone do not establish activity intensity or strengthening coverage |
| What was my session training load? | Some durations and set effort notes | Explicit numerical whole-session RPE and the matching session duration |
| How much time was easy or hard? | Activity average and maximum heart rate | Time-resolved intensity, individual zone boundaries, and counting method |
| How is my fitness changing? | Dated Garmin VO2 reports, generic/cycling category | Comparable conditions and source; a report date is not a proven measurement date |
| What protein range applies? | Body weight | Goal, applicability of the evidence, and fat-free mass for an FFM-based formula |
| Am I under-fueled? | Weight and some activity estimates | Intake and clinical context; existing records do not establish a diagnosis |

## Loading evidence on demand

1. Find the question in the [wiki index](../README.md).
2. Read the relevant topic page and linked source note.
3. Check coverage, population, units, assumptions, and any conflicting evidence.
4. Read the cited PDF pages when the note does not resolve the question.
5. Query relevant workout records. Ask for missing material inputs rather than
   inventing numerical equivalents for conversational descriptions.
6. Separate recorded facts, calculations, and proposed training choices in the
   answer. Cite the source behind a numerical recommendation.

Original PDFs are local files under `resources/sources/`, ignored by Git. Source
notes should also carry public bibliographic links so the wiki remains useful
without those files. PDF text extraction can corrupt symbols and table columns;
verify equations and ambiguous numerical values against the page image.

## Data boundaries

Garmin heart-rate zones are a candidate for extending the imports. Check the
available API responses for configured boundaries and activity time in zones.
Preserve the activity, sport, zone definition (for example, percentage of maximum
heart rate or heart-rate reserve), units, and observation date. Current settings
may differ from those used for an older activity. Garmin zone numbers must not
be treated as equivalent to a paper's zone numbers without checking boundaries.
API availability and historical settings support remain unverified here.

Keep Garmin's values identified as Garmin observations. These research sources
do not establish Body Battery thresholds for changing training. Preserve missing
values as unknown and include source dates when discussing stored observations.

Set effort in the user's words is valuable on its own. Do not convert it to a
numerical session RPE, repetitions in reserve, or a diagnostic score without an
explicit report or an independently justified method.

Before adding an executable calculator, identify a repeated use, verify its
formula and inputs, and test unit handling and missing-data behavior. The current
collection is a reference, not an implemented calculator.

# Numerical reference

This index routes a calculation or numerical question to its source note. Read
that note before applying the value: it holds the population, page citations,
measurement definitions, and limitations. These are not implemented calculators.

Every denominator must be positive. An empty classified total makes an intensity
share unknown; missing or invalid fat-free mass prevents an FFM-based calculation.

## Calculations and accounting

| Quantity | Expression | Inputs and limits | Source |
| --- | --- | --- | --- |
| Repetition volume | `sum(reps)` | Included sets must be defined; unknown reps are not zero | [Haff and Triplett](../sources/haff-triplett-essentials-strength-conditioning-4ed.md) |
| Volume-load | `sum(load × reps)` | Consistent units, comparable equipment; not calories or mechanical work | [Haff and Triplett](../sources/haff-triplett-essentials-strength-conditioning-4ed.md) |
| Average load per repetition | `volume_load / repetition_volume` | Denominator must be positive | [Haff and Triplett](../sources/haff-triplett-essentials-strength-conditioning-4ed.md) |
| Proposed percentage increase | `load × (1 + percent/100)` | Arithmetic; requires a justified increment and progression context | [ACSM](../sources/acsm-2009-resistance-training-progression.md) |
| Session load | `session_RPE × duration_minutes` | Modified 0–10 whole-session rating; output arbitrary units | [Foster](../sources/foster-2001-monitoring-exercise-training.md) |
| Target HR by fraction of maximum | `fraction × HRmax` | Beats/min; this is not HR reserve; maximum needs provenance | [Helgerud](../sources/helgerud-2007-aerobic-high-intensity-intervals.md) |
| Intensity share | `100 × classified category / total classified` | Use either sessions or minutes consistently; report missing coverage | [Seiler](../sources/seiler-training-intensity-distribution.md) |
| Moderate-equivalent minutes | `moderate_minutes + 2 × vigorous_minutes` | Approximate health-guideline accounting; avoid duplicate activities | [HHS](../sources/hhs-2018-physical-activity-guidelines-2ed.md) |
| Protein amount | `FFM_kg × coefficient` | Coefficient is g/kg FFM/day; applicability must be established | [Helms](../sources/helms-2014-protein-during-caloric-restriction.md) |
| Energy availability | `(intake − exercise_expenditure) / FFM_kg` | kcal/kg FFM/day; substantial measurement limitations; not a diagnostic score | [IOC](../sources/mountjoy-2023-ioc-reds-consensus.md) |

## Ranges and protocols

| Question | Where to look | Why the surrounding text matters |
| --- | --- | --- |
| Loading, frequency and progression percentages | [ACSM](../sources/acsm-2009-resistance-training-progression.md) | Historical 2009 guidance; 2026 update not fully indexed |
| Dose-response peaks | [Rhea](../sources/rhea-2003-strength-dose-response-meta-analysis.md) | Pooled categories; sets per muscle per workout |
| Interval work, recovery and intensity | [Helgerud](../sources/helgerud-2007-aerobic-high-intensity-intervals.md), [Arboleda-Serna](../sources/arboleda-serna-2019-hiit-vs-continuous-training.md) | Experimental protocols in different populations |
| Easy-running intensity ranges | [Daniels](../sources/daniels-2022-running-formula-4ed.md) | Coaching guidance, not personal measured breakpoints |
| Protein range during energy restriction | [Helms](../sources/helms-2014-protein-during-caloric-restriction.md) | Fat-free mass denominator; limited older review |
| Weekly activity amounts | [HHS](../sources/hhs-2018-physical-activity-guidelines-2ed.md) | Health benefits, not a performance optimum |

## Incomplete or unsuitable calculator specifications

- Rhea's standardized effect size uses study-group means and variability, and
  its full correction is not specified by the extraction. It is not a personal
  two-workout progress score.
- Daniels' VDOT relationship is conceptual here. Fitted functions and tables
  have not been extracted or validated.
- Foster's monotony and strain examples need visual verification before reuse.
- The IOC's historical energy-availability threshold is not a universal
  diagnostic cutoff. No Garmin Body Battery training threshold is supported by
  this collection.

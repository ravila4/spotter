# Foster et al. (2001): monitoring exercise training

- **Source:** *A New Approach to Monitoring Exercise Training*. Journal of Strength and Conditioning Research 15(1), 109–115.
- **Original:** [local PDF](../../resources/sources/foster-2001-monitoring-exercise-training.pdf).
- **Public record:** [PubMed](https://pubmed.ncbi.nlm.nih.gov/11708692/).
- **Type:** Small validation study, not a training prescription or injury prediction model.
- **Coverage:** Targeted reading of methods and practical applications, printed pp. 110–114 (PDF pp. 2–6), plus abstract. Seven-page scanned PDF has imperfect OCR. Detailed table values and regression coefficients were not transcribed.

## Findings and numbers

| Finding | Population and limits | Location |
| --- | --- | --- |
| Session effort can combine with duration to describe training load. | Twelve trained recreational cyclists (six men, six women), plus 14 collegiate male basketball players. Generalization to other populations needs support. | Printed p. 110; PDF p. 2 |
| Ask for one overall numerical session rating on the modified 0–10 scale, approximately 30 minutes after finishing. | The delay was chosen to reduce the influence of the final part of the workout. It describes this measurement protocol, not proof that every other collection time is invalid. | Printed p. 111, Figure 1 and methods; PDF p. 3 |
| Session-RPE and heart-rate-zone scores tracked one another, but their absolute values differed. | This supports tracking within a consistent method; it does not make either score interchangeable with Garmin training load. | Printed pp. 112–113; PDF pp. 4–5 |

## Calculation

`session_load = session_RPE × duration_minutes`

- `session_RPE`: user's numerical rating of the whole session on the study's modified 0–10 scale.
- `duration_minutes`: duration of that training bout, with a consistent policy for rests and pauses.
- Output: arbitrary load units (AU), not calories or a physiological quantity.
- Location: printed p. 111 (PDF p. 3); practical use on p. 114 (PDF p. 6).
- Illustrative calculation, not study data: a 40-minute session rated 5 gives 200 AU.
- Weekly load can sum known session loads. Missing sessions or ratings must remain missing, not become zero-load rest days.

The paper also illustrates monotony and strain (printed p. 114, PDF p. 6). They are not extracted here: the scanned table has OCR errors and needs visual verification before its formulas or example values are reused. The paper does not establish a clinical alarm threshold for Spotter.

## Use in Spotter

Useful for asking how hard an entire workout felt and comparing recorded weekly effort. Existing free-text **set effort** cannot be converted into this number or averaged into a session rating. Actual session duration is also required; elapsed timestamps with uncertain pauses are insufficient without clarification.

This is a candidate calculation, not an implemented field or command. Preserve the rating scale, collection time, duration definition, and missingness if it is implemented.

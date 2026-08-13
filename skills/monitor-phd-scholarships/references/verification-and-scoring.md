# Verification and scoring

## Contents

- Verification packet
- Hard gates
- Funding models
- Deadline rules
- Eligibility comparison
- Match rubric
- Critical review

## Verification packet

Evaluate a candidate from current, direct evidence. Preserve concise evidence summaries rather than large copied passages. Each evidence item must state:

- fact type;
- URL;
- authority level;
- checked timestamp;
- concise supporting summary;
- any conflict or uncertainty.

Required fact types for publication are `OFFICIAL_POSTING`, `DEADLINE`, `FUNDING`, `ELIGIBILITY`, and `APPLICATION`. One page may support several facts, but create distinct evidence entries so each gate is auditable.

## Hard gates

Apply these before academic-fit scoring:

1. **Doctoral identity**: It is an actual PhD/doctorate opening, not a postdoctoral job, staff role requiring a PhD, generic supervisor profile, expired news item, or unfunded expression of interest.
2. **Country scope**: The host location is in a currently configured country.
3. **Current actionability**: The authoritative deadline is in the future, or the position is explicitly open until filled. Registration dates and publication dates are not application deadlines.
4. **Application path**: A current official or institution-authorized application route exists.
5. **Funding**: The funding route satisfies the configured policy, including tuition, stipend/salary, international-fee rules, duration, and any separate application.
6. **Eligibility**: Every explicit degree, discipline, completion-date, grade, nationality/residency, language, start-date, and other mandatory rule is satisfied by confirmed profile evidence.
7. **No explicit disqualifier**: No authoritative rule contradicts the confirmed profile.
8. **Evidence consistency**: No unresolved conflict affects the deadline, funding, eligibility, host, or application route.

Outcomes:

- Confirmed pass: continue to scoring.
- Confirmed failure: `REJECT`.
- Missing or conflicting load-bearing evidence: `HOLD`.

Never interpret “not stated” as “satisfied.”

## Funding models

Classify exactly one route:

- `SALARY`: doctoral employment with salary.
- `PROJECT_ATTACHED`: grant/studentship attached to the advertised project.
- `GUARANTEED_PROGRAM`: programme funding guaranteed to admitted eligible students.
- `AUTOMATIC_CONSIDERATION`: admission automatically triggers scholarship consideration; verify whether funding is guaranteed or competitive.
- `SEPARATE_APPLICATION`: a distinct scholarship application is mandatory.
- `COMPETITIVE`: funding is limited and not assured.
- `SELF_FUNDED`: applicant must provide funding.
- `UNKNOWN`: current evidence does not establish the route.

“Funding available,” “funding may be available,” and a general scholarship list do not establish that this applicant and project are funded. If funding is separate, record both programme and funding deadlines and use the earliest mandatory date as `effective_action_deadline`.

When `fully_funded_required=true`, verify:

- full tuition coverage;
- stipend or salary coverage;
- international fee coverage when the applicant would pay international fees and the configuration requires it;
- funded duration or any material gap.

When a minimum stipend is configured, record amount, ISO currency, and payment period from authoritative evidence. Compare only like-for-like currency and period. If conversion would be necessary, hold for explicit configuration rather than applying a guessed exchange rate or gross/net conversion.

Unknown coverage produces `HOLD`, not publication.

## Deadline rules

Capture the deadline exactly as the authoritative source states it.

- Use ISO 8601 in state: `YYYY-MM-DD` for date-only or an offset-bearing datetime such as `2026-10-01T17:00:00+02:00`.
- Record `deadline_precision` as `DATE`, `DATETIME`, `ROLLING`, or `UNKNOWN`.
- Record the named timezone separately when stated.
- For date-only deadlines, treat the date as open through that date in the configured timezone; do not invent a time.
- For `OPEN_UNTIL_FILLED`, require explicit current wording and reverify on the active cadence.
- When pages conflict, use `CONFLICT` and hold the candidate until resolved.
- When a scholarship and programme have different deadlines, retain both and use the earliest mandatory one.
- The tracker derives `effective_action_deadline` from the component programme/position and funding deadlines. A supplied value that is not the earliest causes `HOLD`; it cannot hide an earlier deadline.
- A past or equal-to-past offset datetime is expired. A date earlier than the current local date is expired.

## Eligibility comparison

Build a requirement matrix for each candidate:

| Requirement | Authoritative evidence | Confirmed profile evidence | Result |
|---|---|---|---|
| Degree level/status | Exact requirement | Degree and completion date | Pass/fail/unknown |
| Discipline | Required/accepted fields | Confirmed degree fields | Pass/fail/unknown |
| Grade | Threshold and scale | Confirmed grade and scale | Pass/fail/unknown |
| Research/methods | Mandatory capabilities | CV/user-confirmed evidence | Pass/fail/unknown |
| Language | Test/waiver rule | Confirmed test or waiver | Pass/fail/unknown |
| Nationality/residency | Funding/admission restriction | User-confirmed facts | Pass/fail/unknown |
| Start/availability | Mandatory date | Confirmed availability | Pass/fail/unknown |
| Other | Explicit mandatory rule | Confirmed evidence | Pass/fail/unknown |

Do not convert “preferred,” “desirable,” or “advantageous” criteria into eligibility gates. Include them in fit only when relevant.

## Match rubric

After all hard gates pass, score fit from 0 to 100:

| Component | Maximum | Measure |
|---|---:|---|
| Topic alignment | 35 | Direct overlap between project questions/domain and confirmed interests, thesis, projects, or publications |
| Methods and skills | 25 | Demonstrated methods, tools, data types, laboratory or analytical techniques |
| Research experience | 20 | Strength and relevance of completed research, publications, projects, and research employment |
| Academic preparation | 15 | Relevance and depth of degree-level preparation beyond the minimum eligibility gate |
| User preferences | 5 | Confirmed location, start, topic, or work-arrangement preferences |

For each component record points, maximum, and specific CV/project evidence. The tracker requires component points to sum exactly to `current_match_score`.

Do not add points for:

- source quality or verification completeness;
- university prestige or rankings unless the user explicitly makes it a preference;
- citation counts unrelated to fit;
- protected characteristics;
- speculative supervisor interest;
- presumed admission chance.

Store evidence quality separately as `verification_confidence` from 0 to 100. Publication requires the configured confidence threshold as well as match score threshold.

## Critical review

Before publication, conduct a second review separated from discovery/scoring.

First write the normalized candidate JSON with `review=null` and run the tracker's `review-subject` command. The verifier must review that exact packet, direct evidence set, and returned CV/profile/config-bound subject hash. Store a nonblank reviewer ID and copy the exact hash into `review.subject_hash`. A review from another candidate, an earlier evidence snapshot, or a different CV/profile/configuration is invalid. If any candidate, evidence, score, identity, or runtime-context field changes after review, recompute the hash and repeat the review.

The critic must check:

- direct official and application URLs work and refer to the same vacancy;
- deadline interpretation and timezone;
- programme versus funding deadline;
- guaranteed, automatic, competitive, and separate funding distinctions;
- international tuition/fee coverage;
- every mandatory eligibility row against confirmed profile evidence;
- score arithmetic and evidence;
- duplicate/repost identity;
- main risk and short explanation;
- absence of unsupported claims.

Use `INDEPENDENT_AGENT` when a distinct verifier performs the review and identify that verifier in `reviewer_id`. Use `SELF_SECOND_PASS` only when no separate agent is available, using a clear self-review identifier. Publication requires verdict `PASS`; `HOLD` or `FAIL` cannot be overridden by enthusiasm or score.

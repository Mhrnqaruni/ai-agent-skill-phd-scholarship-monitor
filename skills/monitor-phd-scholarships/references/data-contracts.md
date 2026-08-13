# Tracker and data contracts

## Contents

- Command conventions
- Workspace commands
- Daily-run commands
- Candidate packet
- Coverage packet
- CSV and report contracts

## Command conventions

Use Python 3.10 or newer. Resolve the installed skill directory first, then invoke:

```text
python <SKILL_DIR>/scripts/phd_tracker.py --workspace <PRIVATE_WORKSPACE> <command> [options]
```

Every successful command prints JSON. A nonzero exit code means the requested state transition did not complete. Do not parse human assumptions from an error; repair it or abort the run.

SQLite is the canonical state. Do not modify `tracker.sqlite3`, `opportunities.csv`, reports, locks, or logs outside the tracker.

## Workspace commands

Initialize a new private workspace:

```text
python <SCRIPT> --workspace <WORKSPACE> init \
  --country Netherlands --country Germany \
  --timezone Asia/Singapore --daily-time 12:00
```

PowerShell uses backticks or a single line instead of backslashes.

Initialization refuses a nonempty directory and creates:

```text
input/
backups/
reports/
logs/
config.json
profile.json
tracker.sqlite3
opportunities.csv
.gitignore
```

Place the CV in `input/`, complete and confirm `profile.json`, then validate:

```text
python <SCRIPT> --workspace <WORKSPACE> validate
```

Use `validate --allow-unconfirmed` only while constructing the profile. Never search or schedule with an unconfirmed profile.

Re-export the cumulative CSV after closing a locked spreadsheet:

```text
python <SCRIPT> --workspace <WORKSPACE> export
```

Inspect aggregate state without changing it:

```text
python <SCRIPT> --workspace <WORKSPACE> stats
```

## Daily-run commands

Start exactly one run:

```text
python <SCRIPT> --workspace <WORKSPACE> run-start
```

Retain the returned `run_id`. Inspect due records:

```text
python <SCRIPT> --workspace <WORKSPACE> due --run-id <RUN_ID>
```

Check whether a discovery is already known:

```text
python <SCRIPT> --workspace <WORKSPACE> lookup --url <URL>
```

Optional identity signals:

```text
--official-id <ID> --university <NAME> --title <TITLE> \
--research-topic <TOPIC> --department <NAME> --city <CITY> \
--country <COUNTRY> --supervisor <NAME> --deadline <ISO_VALUE>
```

When a known candidate is observed but is unchanged and not due:

```text
python <SCRIPT> --workspace <WORKSPACE> touch \
  --run-id <RUN_ID> --record-id <RECORD_ID> --url <OBSERVED_URL>
```

After full evaluation, write a candidate packet to a temporary JSON file and run:

```text
python <SCRIPT> --workspace <WORKSPACE> candidate-upsert \
  --run-id <RUN_ID> --file <CANDIDATE_JSON>
```

Finish with coverage:

```text
python <SCRIPT> --workspace <WORKSPACE> run-finish \
  --run-id <RUN_ID> --coverage <COVERAGE_JSON>
```

On unrecoverable interruption:

```text
python <SCRIPT> --workspace <WORKSPACE> run-abort \
  --run-id <RUN_ID> --reason "Concise failure reason"
```

## Candidate packet

Use this complete shape for a potentially publishable candidate. Use JSON `null` for unknown values; do not invent placeholders.

```json
{
  "record_id": null,
  "official_id": "REQ-1234",
  "title": "Doctoral Researcher in Example Topic",
  "research_topic": "Concise normalized topic",
  "university": "Example University",
  "department": "Department of Example",
  "city": "Example City",
  "country": "Netherlands",
  "supervisor": "Professor Example",
  "doctoral_status": "CONFIRMED",
  "application_status": "VERIFIED",
  "program_deadline": "2026-10-01T17:00:00+02:00",
  "funding_deadline": null,
  "effective_action_deadline": "2026-10-01T17:00:00+02:00",
  "deadline_timezone": "Europe/Amsterdam",
  "deadline_precision": "DATETIME",
  "deadline_status": "OPEN",
  "funding_route": "SALARY",
  "funding_status": "VERIFIED",
  "funding_summary": "Salary and contract duration stated on official vacancy page.",
  "tuition_coverage": "FULL",
  "stipend_coverage": "FULL",
  "international_fee_coverage": "FULL",
  "stipend_amount": 3500,
  "stipend_currency": "EUR",
  "stipend_period": "MONTH",
  "eligibility_status": "ELIGIBLE",
  "eligibility_summary": "Every mandatory rule compared against confirmed profile facts.",
  "verification_confidence": 92,
  "score": {
    "topic_alignment": {
      "points": 31,
      "max": 35,
      "evidence": "Specific project/profile overlap"
    },
    "methods_and_skills": {
      "points": 22,
      "max": 25,
      "evidence": "Specific demonstrated methods"
    },
    "research_experience": {
      "points": 17,
      "max": 20,
      "evidence": "Specific research evidence"
    },
    "academic_preparation": {
      "points": 13,
      "max": 15,
      "evidence": "Specific degree evidence"
    },
    "user_preferences": {
      "points": 4,
      "max": 5,
      "evidence": "Specific confirmed preference"
    }
  },
  "short_match_explanation": "Two or three clear sentences grounded in evidence.",
  "main_risk": "Most material limitation, or 'No material limitation identified.'",
  "official_posting_url": "https://official.example/jobs/REQ-1234",
  "application_url": "https://apply.official.example/REQ-1234",
  "funding_url": "https://official.example/jobs/REQ-1234#conditions",
  "discovery_urls": [
    "https://discovery.example/item/1234"
  ],
  "content_hash": null,
  "duplicate_review": null,
  "evidence": [
    {
      "fact": "OFFICIAL_POSTING",
      "url": "https://official.example/jobs/REQ-1234",
      "authority": "PRIMARY",
      "checked_at": "2026-08-13T12:10:00+08:00",
      "summary": "Official page identifies a current doctoral vacancy."
    },
    {
      "fact": "DEADLINE",
      "url": "https://official.example/jobs/REQ-1234",
      "authority": "PRIMARY",
      "checked_at": "2026-08-13T12:10:00+08:00",
      "summary": "Applications close 1 October 2026 at 17:00 CEST."
    },
    {
      "fact": "FUNDING",
      "url": "https://official.example/jobs/REQ-1234",
      "authority": "PRIMARY",
      "checked_at": "2026-08-13T12:10:00+08:00",
      "summary": "Official conditions state salary and funded duration."
    },
    {
      "fact": "ELIGIBILITY",
      "url": "https://official.example/jobs/REQ-1234",
      "authority": "PRIMARY",
      "checked_at": "2026-08-13T12:10:00+08:00",
      "summary": "Mandatory degree and skill requirements were checked."
    },
    {
      "fact": "APPLICATION",
      "url": "https://apply.official.example/REQ-1234",
      "authority": "AUTHORIZED_ATS",
      "checked_at": "2026-08-13T12:10:00+08:00",
      "summary": "The institution-authorized application route is currently available."
    }
  ],
  "review": {
    "mode": "INDEPENDENT_AGENT",
    "verdict": "PASS",
    "reviewed_at": "2026-08-13T12:20:00+08:00",
    "notes": "Independent hard-gate, provenance, duplicate, and score check passed."
  },
  "rejection_reason": null
}
```

Allowed values:

- `doctoral_status`: `CONFIRMED`, `NOT_DOCTORAL`, `UNKNOWN`, `CONFLICT`
- `application_status`: `VERIFIED`, `NOT_VERIFIED`, `CONFLICT`
- `deadline_precision`: `DATE`, `DATETIME`, `ROLLING`, `UNKNOWN`
- `deadline_status`: `OPEN`, `OPEN_UNTIL_FILLED`, `CLOSED`, `EXPIRED`, `UNKNOWN`, `CONFLICT`
- `funding_route`: `SALARY`, `PROJECT_ATTACHED`, `GUARANTEED_PROGRAM`, `AUTOMATIC_CONSIDERATION`, `SEPARATE_APPLICATION`, `COMPETITIVE`, `SELF_FUNDED`, `UNKNOWN`
- `funding_status`: `VERIFIED`, `NOT_VERIFIED`, `INELIGIBLE`, `CONFLICT`
- coverage values: `FULL`, `PARTIAL`, `NONE`, `NOT_APPLICABLE`, `UNKNOWN`
- `stipend_period`: `YEAR`, `MONTH`, `WEEK`, `HOUR`, `TOTAL`, `UNKNOWN`
- `eligibility_status`: `ELIGIBLE`, `INELIGIBLE`, `UNKNOWN`, `CONFLICT`
- evidence `fact`: `OFFICIAL_POSTING`, `DEADLINE`, `FUNDING`, `ELIGIBILITY`, `APPLICATION`, `LOCATION`, `OTHER`
- evidence `authority`: `PRIMARY`, `AUTHORIZED_ATS`, `NATIONAL_PORTAL`, `SECONDARY`
- review `mode`: `INDEPENDENT_AGENT`, `SELF_SECOND_PASS`
- review `verdict`: `PASS`, `HOLD`, `FAIL`

For an early hard-gate rejection, score and review may be `null`, but include the evidence establishing rejection and a precise `rejection_reason`. For a hold, include every established field plus the unresolved fact. The tracker derives `PUBLISH`, `UNDER_THRESHOLD`, `HOLD`, or `REJECT`; the packet does not choose the decision.

`content_hash` must be `null` or omitted; the tracker computes it from the normalized material packet and never trusts a caller-supplied value. When `lookup` reports possible fingerprint duplicates but no strong identity match, inspect them before writing. To create a genuinely distinct record, provide:

For a fixed deadline, put the vacancy/admission deadline in `program_deadline` and any separate funding deadline in `funding_deadline`. `effective_action_deadline` must repeat the earlier mandatory component; the tracker derives and checks it. For explicit open-until-filled positions, use `deadline_status=OPEN_UNTIL_FILLED`, `deadline_precision=ROLLING`, and null component/effective deadlines.

```json
{
  "duplicate_review": {
    "verdict": "DISTINCT",
    "record_ids": ["phd-existing-record"],
    "reviewed_at": "2026-08-13T12:15:00+08:00",
    "reason": "Different official host project and application route; not a repost or alias."
  }
}
```

To merge with an existing vacancy, supply its trusted `record_id` instead. Never use a fingerprint alone as decisive identity.

## Coverage packet

```json
{
  "countries": {
    "Netherlands": {
      "status": "COMPLETE",
      "notes": "Core sweep and planned queries completed.",
      "sources": [
        {
          "name": "Example University vacancies",
          "url": "https://official.example/jobs",
          "class": "OFFICIAL",
          "status": "OK",
          "checked_at": "2026-08-13T12:30:00+08:00",
          "candidates_seen": 4,
          "note": ""
        }
      ]
    }
  }
}
```

Allowed country status: `COMPLETE`, `PARTIAL`, `FAILED`. Allowed source status: `OK`, `PARTIAL`, `FAILED`. The tracker downgrades a country marked complete when any included required source is partial/failed and inserts a failed entry for any configured country omitted from the packet.

## CSV and report contracts

The cumulative CSV contains only records that qualified for publication at least once. It retains them after closure, expiry, scope changes, or rescoring. It sorts by newest first-seen date, then current score descending, then earliest effective deadline.

Columns:

```text
record_id
first_seen_date
last_verified_date
last_changed_date
status
is_new_today
score_at_discovery
current_match_score
verification_confidence
eligibility_status
funding_route
funding_summary
title
research_topic
university
department
city
country
supervisor
program_deadline
funding_deadline
effective_action_deadline
deadline_status
short_match_explanation
main_risk
official_posting_url
application_url
funding_url
evidence_urls
profile_version
scoring_version
```

The daily report contains:

- run ID, local time, and overall coverage status;
- coverage table for every country;
- newly published candidates;
- materially updated previously published candidates;
- previously published candidates closing soon;
- source failures and limitations;
- internal counts for holds, rejections, and under-threshold candidates without cluttering the recommendation list;
- paths to the cumulative CSV and canonical database.

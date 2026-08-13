# Intake and configuration

## Contents

- Setup decisions
- CV extraction
- Profile confirmation
- Configuration contract
- Change handling

## Setup decisions

Resolve these items before the first baseline search. Ask concise questions and reuse facts already supplied by the user.

1. Private workspace path.
2. Target countries, using unambiguous English country names.
3. Daily run time and IANA timezone, such as `12:00` and `Asia/Singapore`.
4. Funding policy:
   - fully funded or salaried positions only;
   - whether guaranteed programme funding is accepted;
   - whether automatic scholarship consideration is accepted despite funding uncertainty;
   - whether separate or competitive scholarship applications are accepted;
   - whether international tuition/fees must be covered;
   - optional stipend floor and currency.
5. Eligibility facts:
   - nationality or nationalities;
   - current residency and any permanent-residency status;
   - completed and in-progress degrees with dates, field, institution, and grade scale;
   - English-language tests, dates, scores, and confirmed waivers;
   - desired start window and visa constraints the user explicitly identifies.
6. Fit preferences:
   - research interests and synonyms;
   - preferred methods and tools;
   - excluded topics, institutions, cities, or arrangements;
   - optional minimum application lead time.

Do not infer nationality, residency, disability, race, ethnicity, religion, age, gender, family status, health, or other protected/sensitive facts. Use a sensitive fact only when the user explicitly provides it and an authoritative eligibility rule makes it necessary.

## CV extraction

Place the CV in `<workspace>/input/` and retain the original locally. Extract a structured profile from explicit text:

- education and completion status;
- thesis/dissertation titles and topics;
- research interests;
- methods and research designs;
- software, programming languages, laboratory tools, and statistical techniques;
- publications, preprints, presentations, and projects;
- research and relevant professional experience;
- languages and formal test results;
- awards and other relevant evidence.

For each extracted fact, record a provenance value:

- `CV`: stated in the CV;
- `USER_CONFIRMED`: supplied or corrected by the user;
- `UNKNOWN`: not established.

Do not turn absence into a negative fact. For example, a CV that omits nationality does not establish any nationality.

The tracker hashes the relative filename, size, and bytes of every supported CV file in `input/`. Do not edit or replace those files during a live run. After any CV change, re-extract the profile and obtain fresh confirmation; changing the CV alone causes the next run to stop rather than use stale fit or eligibility facts.

## Profile confirmation

Create `profile.json` using this minimum shape. Additional structured fields are allowed.

```json
{
  "schema_version": 1,
  "confirmed_by_user": false,
  "confirmed_at": null,
  "eligibility": {
    "nationalities": [],
    "residencies": [],
    "work_or_study_rights": [],
    "language_evidence": []
  },
  "education": [],
  "research_interests": [],
  "methods": [],
  "tools": [],
  "publications_and_projects": [],
  "experience": [],
  "preferences": {
    "desired_start_window": null,
    "excluded_topics": [],
    "excluded_institutions": []
  },
  "fact_provenance": []
}
```

Show the completed structure to the user. Apply corrections and ask for explicit confirmation. Only then set:

```json
{
  "confirmed_by_user": true,
  "confirmed_at": "2026-08-13T12:00:00+08:00"
}
```

The tracker computes the profile hash; do not invent or manually preserve one.

## Configuration contract

`phd_tracker.py init` creates `config.json`. Preserve its keys and use JSON, not YAML, so the bundled standard-library tracker can validate it without dependencies.

Important fields:

- `countries`: current search scope; read it on every run.
- `timezone` and `daily_time`: human schedule contract.
- `minimum_match_score`: must be at least 80.
- `minimum_verification_confidence`: evidence threshold independent of fit.
- `scoring_version`: increment after changing weights or interpretation.
- `funding_policy.accepted_routes`: accepted funding mechanisms. The safe default excludes competitive and automatic-consideration routes unless the user knowingly opts in.
- `funding_policy.fully_funded_required`: require tuition and stipend coverage.
- `funding_policy.international_fees_required`: require explicit international-fee coverage when applicable.
- `funding_policy.minimum_stipend`, `minimum_stipend_currency`, and `minimum_stipend_period`: an optional directly comparable floor; do not perform hidden currency or period conversion.
- `search.closing_soon_days`: daily-report warning window.
- `search.reverify_active_days`: normal active-record verification interval.
- `search.reverify_closing_days`: near-deadline verification interval.
- `search.max_run_hours`: stale-run lock recovery boundary.
- `source_registry`: country-specific official, national, and discovery sources. Every `required_core_sources` entry must be an object with a stable `name` and canonical `url`.

The schedule prompt must never hardcode countries. It must read the current configuration each day.

## Change handling

### Country changes

- Compare countries case-insensitively.
- Run a full baseline search for every added country.
- Retain removed-country rows and set `in_scope=false`.
- Do not delete history when a country is removed.
- Update the source registry when country scope changes.

### CV or profile changes

- Re-extract only after reading the updated CV or receiving confirmed corrections.
- Ask the user to confirm the new structured profile and set `confirmed_at` to that real confirmation time.
- Let `run-start` detect the new profile hash.
- Reassess every active, rolling, closing-soon, and held record affected by the changed facts.
- Preserve score-at-discovery and evaluation history.

### Schedule changes

Update both `config.json` and the actual scheduled task. If only one changes, report a configuration mismatch and do not imply the schedule was updated.

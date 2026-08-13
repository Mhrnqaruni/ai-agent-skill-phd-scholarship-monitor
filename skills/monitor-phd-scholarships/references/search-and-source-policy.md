# Search and source policy

## Contents

- Coverage objective
- Source hierarchy
- Country search plan
- Query design
- Subagent discovery contract
- Coverage record

## Coverage objective

Search the configured source set rigorously; do not claim to search the entire internet. A trustworthy run records what succeeded, what failed, and what was not attempted.

Use two layers:

1. Daily core sweep of authoritative and high-yield sources in every configured country.
2. Rotating deep sweep of universities, doctoral schools, funders, and alternative terminology over the configured rotation period.

The absence of a match is reportable only when coverage is recorded. Distinguish:

- `COMPLETE`: all required core sources and planned queries completed.
- `PARTIAL`: some required coverage failed or was deferred.
- `FAILED`: no meaningful current coverage was obtained.

## Source hierarchy

Prefer sources in this order:

1. Official university, institute, doctoral-school, or funder vacancy page.
2. Institution-authorized applicant tracking system linked from the official institution.
3. National or transnational research vacancy portal, such as EURAXESS.
4. Reputable academic vacancy aggregator.
5. Search results, newsletters, social posts, and copied announcements.

Levels 3–5 are discovery aids. Before publishing, trace the candidate to level 1 or 2 and preserve that provenance chain. If no authoritative current page exists, keep the candidate internal on `HOLD` or `REJECT` it as unverifiable.

Prefer structured APIs, RSS, feeds, sitemaps, and JSON-LD where lawfully available. Do not bypass robots controls, CAPTCHAs, paywalls, authentication, or rate limits. Do not use proxy rotation or anti-detection techniques.

## Country search plan

For each country, maintain `source_registry` entries covering as available:

- national research-job portal;
- major doctoral vacancy portal;
- university vacancy pages and doctoral schools;
- public research institutes;
- major public or charitable funding bodies;
- high-yield aggregators for discovery;
- local-language doctoral job titles and funding terms.

At the beginning of each run:

1. Load the current countries from `config.json`.
2. Load profile topics, methods, fields, and synonyms.
3. Load known aliases and due records from SQLite.
4. Establish the source and query plan for each country.

Before the baseline run, save at least one meaningful required core source for every configured country. Store every required source as an object containing both a stable display name and canonical URL; only that normalized URL satisfies coverage—the free-form name cannot substitute for it. In practice, use multiple complementary official/national sources where available. The tracker refuses `COMPLETE` coverage for an empty required-source registry or an empty source record.

At the end of the run, provide a coverage entry for every configured country even if zero candidates were discovered.

## Query design

Build query families from the confirmed profile rather than one exact phrase:

- doctoral titles: `PhD`, `doctoral researcher`, `doctoral candidate`, `doctoral student`, `research assistant PhD`, and verified local-language equivalents;
- funding terms: `funded`, `studentship`, `scholarship`, `stipend`, `salary`, `doctoral fellowship`, and local equivalents;
- research topics and close synonyms;
- methods, datasets, laboratory techniques, or tools demonstrated in the profile;
- institution and site filters for official domains;
- year/start-cycle terms where helpful.

Avoid acronym-only searches when an acronym is ambiguous. Expand acronyms and pair them with the discipline. Do not put the applicant's name, email, phone number, CV text, or sensitive eligibility data into search queries.

Use aggregators to widen recall, then verify candidates on authoritative pages. Search snippets alone never establish an open deadline, eligibility, or funding.

## Subagent discovery contract

When subagents are available, distribute country/source discovery without leaking the full CV.

Give each researcher:

- assigned country or source group;
- redacted profile topics, methods, degree field, and explicit constraints;
- current date/timezone;
- known URLs or IDs to avoid repeating;
- requirement to return candidate URLs, source type, discovery query/source, and concise evidence notes.

Require this output per candidate:

```text
title
university/institute
country/city if stated
discovery URL
official URL if found
apparent deadline
apparent funding route
why it may match
facts still unverified
```

Researchers do not score definitively, update state, or declare eligibility. The lead agent deduplicates and verifies.

For a potentially publishable candidate, use a different verifier agent when possible. Give that verifier the candidate packet, the minimal confirmed profile facts, and direct sources—not the discovery agent's conclusion. Require `PASS`, `HOLD`, or `FAIL` with exact reasons. The lead remains responsible for the final packet and database write.

## Coverage record

Use the coverage JSON defined in `data-contracts.md`. For every source record:

- source name and URL;
- source class (`OFFICIAL`, `AUTHORIZED_ATS`, `NATIONAL_PORTAL`, `AGGREGATOR`, or `SEARCH`);
- `OK`, `PARTIAL`, or `FAILED` status;
- checked time;
- discovered-candidate count;
- error or limitation, if any.

Do not mark a country `COMPLETE` when a required core source failed. Do not describe a zero-candidate run as successful without showing coverage.

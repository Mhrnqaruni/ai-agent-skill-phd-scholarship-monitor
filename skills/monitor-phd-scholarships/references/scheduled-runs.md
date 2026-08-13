# Scheduled runs

## Contents

- Prerequisites
- First-run gate
- Scheduled-task configuration
- Daily procedure
- Schedule changes
- Expected outputs

## Prerequisites

Use a Codex/ChatGPT desktop scheduled task for a private local workspace. A web-only scheduled task cannot directly maintain local SQLite and CSV files. The local computer must be on, the desktop app must be running, and the workspace must be available when the task fires.

The scheduled task requires:

- this skill installed and available as `$monitor-phd-scholarships`;
- a validated private workspace;
- a user-confirmed `profile.json`;
- network access for current web research;
- write access to the private workspace;
- unattended permissions compatible with the required web and local operations.

Designate exactly one computer and one scheduled task as the active owner of the canonical workspace. Do not point concurrent schedules at the same database or put the live SQLite workspace in a multi-writer cloud-sync folder. To transfer ownership, let any current run finish, disable the old schedule, copy and validate the private workspace, and only then enable the replacement schedule.

Official guidance: <https://learn.chatgpt.com/docs/automations>

## First-run gate

Before scheduling:

1. Initialize the workspace.
2. Confirm the extracted profile.
3. Run one complete manual baseline sweep.
4. Inspect at least several accepted, rejected, and held decisions.
5. Verify the CSV opens correctly and prior-state behavior works.
6. Review the generated report and coverage disclosure.
7. Correct the profile, funding policy, source registry, or rubric as needed.

Do not schedule a workflow that has not passed this manual review.

## Scheduled-task configuration

Choose:

- standalone scheduled task for independent daily reports;
- the private workspace as the selected local project;
- local-project mode rather than a new worktree;
- the user's confirmed local time and timezone;
- a daily recurrence;
- the permissions required for network and workspace writes.

Use this prompt:

```text
Use $monitor-phd-scholarships to run today's funded-PhD monitoring workflow in <PRIVATE_WORKSPACE>. Read the current profile and configuration from that workspace; do not rely on prior chat memory. Search every configured country, verify hard eligibility/funding/deadline gates from authoritative pages, update the SQLite ledger and cumulative CSV through the bundled tracker, and return the generated daily report. If any country or required source is incomplete, report PARTIAL or FAILED coverage rather than claiming no matches.
```

Do not embed the country list, CV facts, threshold, or funding routes in this prompt. Those values belong in the workspace configuration and profile so changes take effect on the next run.

## Daily procedure

1. Validate workspace, profile, database integrity, and configuration.
2. Start a run and capture its `run_id`.
3. Inspect profile/country/scoring changes and due records.
4. Search all configured countries and required core sources.
5. Deduplicate discoveries before full evaluation.
6. Reverify due records and evaluate new/changed candidates.
7. Compute each potentially publishable packet's `review-subject` hash, critically review that exact candidate/evidence/profile snapshot, and bind the verdict to the returned hash.
8. Finish the run with full coverage JSON.
9. Return the generated report and paths to the CSV/report.

Treat the configuration, confirmed profile, and CV files as immutable from steps 2–8. If any changes, abort and restart the run; the tracker enforces this snapshot boundary.

If an unrecoverable error occurs after step 2, call `run-abort`. Do not leave a live lock silently.

## Schedule changes

When the user changes the daily time or timezone:

1. Update `config.json`.
2. Update the real scheduled task through the desktop scheduled-task interface.
3. Confirm the next run time to the user.
4. If the interface is unavailable, report that the configuration changed but the actual schedule did not.

When countries change, update only `config.json`; the durable prompt reads the current list automatically. Added countries still require baseline coverage on the next run.

## Expected outputs

Each completed run updates:

- `tracker.sqlite3`: canonical private history;
- `opportunities.csv`: cumulative previously-qualified opportunities, new first;
- `reports/YYYY-MM-DD.md`: user-readable daily report;
- `logs/run-<run_id>.json`: machine-readable run outcome.

A report must state one of:

- newly verified matches found;
- no newly verified matches after complete coverage;
- no publishable result, but coverage was partial;
- run failed before reliable coverage.

Never collapse the last three into “no opportunities today.”

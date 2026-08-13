# State, deduplication, and history

## Contents

- Canonical state
- Identity rules
- Recheck semantics
- Lifecycle and publication history
- Profile and country changes
- Safe output

## Canonical state

Treat `<workspace>/tracker.sqlite3` as the canonical ledger. Treat `opportunities.csv`, Markdown reports, and run logs as derived views.

Store every evaluated discovery, not only user-facing matches. Internal retention prevents the same unsuitable or ineligible opportunity from consuming time every day.

The lead agent is the sole writer. Subagents return evidence packets; they never write SQLite or CSV.

## Identity rules

Resolve candidate identity in this order:

1. Existing `record_id`, when explicitly supplied by a trusted tracker lookup.
2. Official vacancy/requisition ID scoped to the institution or authoritative host.
3. Normalized official or known alias URL.
4. Exact deterministic fingerprint of official ID, institution, title/topic, department/supervisor, location, and deadline/start cycle as a possible-duplicate signal only.

The tracker removes common tracking parameters and URL fragments, but it does not use fuzzy merging. A fingerprint never overwrites a record by itself. If it reports possible duplicates, resolve them explicitly: supply the existing `record_id` to merge, or document why the candidate is distinct.

Model these cases carefully:

- Same vacancy on an aggregator and official site: one record with aliases.
- Same consortium topic at different host institutions: separate records.
- Same title in a new recruitment cycle: new record/version unless the official ID establishes continuity.
- Corrected or moved official URL for the same requisition: same record with a new alias.
- Generic programme page advertising multiple distinct projects: separate records for distinct applications when the host treats them separately.

## Recheck semantics

“Do not check an already checked PhD” means “do not repeat a full evaluation when nothing relevant changed.” It never means “trust the first observation forever.”

Reverify when:

- the record is new;
- the authoritative page or fact packet changed;
- the normal active interval elapsed;
- the position is near its deadline;
- it is open until filled;
- the previous decision was `HOLD` and new evidence may exist;
- the CV/profile hash changed;
- the scoring or funding policy changed;
- the country was newly added;
- a source reports closure, withdrawal, or a changed deadline.

When a known result is rediscovered but is not due, call `touch` to update `last_seen_at` and aliases without modifying `last_verified_at` or the score.

Never close an opportunity because:

- it disappeared from one aggregator;
- one page timed out;
- a source search returned no results once;
- access was blocked;
- a daily run was partial or failed.

Require an authoritative closed/withdrawn status, a passed deadline, or direct re-verification before changing lifecycle accordingly.

## Lifecycle and publication history

Useful lifecycle values include:

- `ACTIVE`
- `CLOSING_SOON`
- `OPEN_UNTIL_FILLED`
- `HOLD`
- `BELOW_CURRENT_THRESHOLD`
- `INELIGIBLE`
- `REJECTED`
- `OUT_OF_SCOPE`
- `CLOSED`
- `EXPIRED`
- `WITHDRAWN`

Keep these timestamps distinct:

- `first_seen_at`: immutable first discovery.
- `last_seen_at`: most recent discovery/source observation.
- `last_verified_at`: most recent complete evidence review.
- `last_changed_at`: most recent material fact, decision, or score change.
- `published_at`: first time the candidate satisfied all publication gates.

Once a candidate has been published, keep it in the cumulative CSV even if it expires, closes, leaves scope, or later falls below the current threshold. Update its status; do not delete it. Never export a candidate that has never passed publication gates.

Retain evaluation history so score/profile changes are auditable. Keep `score_at_discovery` unchanged after first publication and update `current_match_score` separately.

## Profile and country changes

At `run-start`, the tracker compares current configuration and profile hashes with the last completed run.

If the profile changed:

- consider every in-scope active, rolling, closing, and held record due;
- recalculate eligibility and fit from current confirmed facts;
- preserve previous evaluations;
- retain previously published CSV rows even when no longer qualifying.

If countries changed:

- added countries require full baseline coverage;
- removed countries remain in history with `in_scope=false`;
- a later re-added country requires a new baseline sweep;
- country comparisons are case-insensitive, while configured display names are preserved.

## Safe output

The tracker writes SQLite in transactions and exports CSV/report files through temporary files followed by atomic replacement. On Windows, an open CSV may prevent replacement. In that case:

- keep SQLite authoritative and intact;
- report the export failure visibly;
- close the spreadsheet and rerun `export`;
- do not reconstruct state from an older CSV.

CSV output uses UTF-8 with BOM and spreadsheet-formula neutralization. Do not disable that protection for web-derived fields.

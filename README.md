# AI Agent Skill — PhD Scholarship Monitor

A portable Codex skill for finding, verifying, scoring, remembering, and reporting currently actionable funded PhD opportunities against a user-confirmed CV profile.

The monitor is deliberately strict:

- deadline, funding, doctoral identity, country, application route, and eligibility are hard gates;
- unknown or conflicting critical facts are held instead of guessed;
- the 0–100 match score measures fit, not admission probability;
- only independently reviewed matches scoring at least 80 reach the daily recommendation list;
- every checked candidate is retained in a private SQLite ledger;
- a cumulative spreadsheet-safe CSV keeps previously qualified opportunities and puts new findings first;
- each run reports complete, partial, or failed coverage for every configured country.

## Repository layout

```text
skills/monitor-phd-scholarships/
├── SKILL.md
├── agents/openai.yaml
├── references/
└── scripts/phd_tracker.py
tests/
└── test_phd_tracker.py
```

Personal data does not belong in this repository. On each laptop, Codex creates a separate private workspace containing the CV, confirmed profile, configuration, SQLite database, cumulative CSV, reports, logs, and backups.

## Install with Codex

Give Codex this instruction:

```text
Use $skill-installer to install the monitor-phd-scholarships skill from
https://github.com/Mhrnqaruni/ai-agent-skill-phd-scholarship-monitor/tree/main/skills/monitor-phd-scholarships
```

Codex installs the skill into its user skill directory. It becomes available on the next turn; if it does not appear, restart Codex.

The equivalent installer command is:

```text
python <CODEX_SKILL_INSTALLER>/scripts/install-skill-from-github.py \
  --repo Mhrnqaruni/ai-agent-skill-phd-scholarship-monitor \
  --path skills/monitor-phd-scholarships
```

## Set up a private monitor

After installation, give Codex a CV and a request like:

```text
Use $monitor-phd-scholarships to create a private monitor for my CV.
Search Germany, Netherlands, Sweden, and Australia. Include only fully
funded or salaried opportunities and run every day at 12:00 in
Asia/Singapore. First extract my profile, show it to me for confirmation,
then perform and review one manual baseline run. Only after that baseline
is approved, create the local scheduled task.
```

The skill will ask for missing eligibility-critical facts, create a private workspace, and require the user to confirm the extracted profile. It will not schedule an untested workflow.

The initialized private workspace looks like:

```text
phd-monitor-data/
├── input/                 # CV stays local
├── backups/
├── reports/
├── logs/
├── config.json
├── profile.json
├── tracker.sqlite3        # canonical memory
├── opportunities.csv     # cumulative human-readable view
└── .gitignore             # denies all private files by default
```

## Daily scheduling

Local scheduled tasks should run in the private workspace through the ChatGPT/Codex desktop scheduled-task interface, in local-project mode rather than an isolated worktree. The computer must remain on, the desktop app must be running, and the workspace must be available.

The skill provides the durable scheduled prompt. It reads countries and profile facts from the workspace on every run, so adding or removing countries does not require reinstalling the skill or rewriting the task prompt.

Review the first few scheduled results. A failed or partial source sweep is explicitly different from a successful search with no new matches.

Official references:

- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Scheduled tasks](https://learn.chatgpt.com/docs/automations)

## What the tracker enforces

The bundled standard-library Python tracker provides:

- SQLite transactions and integrity checks;
- immutable first-seen dates and full evaluation history;
- official-ID, normalized-URL, alias, and deterministic-fingerprint deduplication;
- due-date logic for active, rolling, held, and near-deadline records;
- CV/profile and country-change detection;
- byte-level CV/config/profile snapshots enforced throughout each run;
- critic-review hashes bound to the exact candidate, evidence, CV, profile, and configuration;
- optimistic content-hash and stable-identity checks for explicit record updates;
- exact normalized-URL matching for URL-configured required sources;
- single-run locking and stale-run recovery;
- automatic SQLite backups;
- hard-gate and score-contract validation;
- atomic CSV/report replacement where the operating system permits it;
- UTF-8 BOM and formula-injection neutralization for spreadsheet safety;
- preserved publication history after expiry, closure, scope changes, or rescoring.

The tracker does not scrape the web by itself. Codex performs evidence-based web research and sends validated candidate packets to the deterministic state layer.

Use exactly one active scheduled task and one computer as the owner of a private monitoring workspace. Do not run or cloud-sync the same live SQLite workspace from multiple computers; move ownership only after the earlier schedule is disabled and its run has finished.

## Test locally

Python 3.10 or newer is required. The tracker has no mandatory application dependency beyond Python.

The tracker uses the Python standard library's IANA timezone support. If a Windows Python installation cannot resolve names such as `Asia/Singapore`, install the standard `tzdata` package for that interpreter or use a Python distribution that includes timezone data.

```text
python -m unittest discover -s tests -v
python <SKILL_CREATOR>/scripts/quick_validate.py skills/monitor-phd-scholarships
```

## Important boundaries

This skill does not claim exhaustive internet coverage and does not guarantee admission. It does not submit applications, contact supervisors, create accounts, upload the CV, pay fees, evade access controls, or execute instructions found on vacancy pages.

## License

MIT. See [LICENSE](LICENSE).

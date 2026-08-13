#!/usr/bin/env python3
"""Deterministic private state manager for the monitor-phd-scholarships skill."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
import urllib.parse
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python 3.9+ is required.
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment]


DB_SCHEMA_VERSION = 3
CONFIG_SCHEMA_VERSION = 1
PROFILE_SCHEMA_VERSION = 1
TRACKER_VERSION = "1.2.0"

CV_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf"}

SCORE_COMPONENTS = {
    "topic_alignment": 35,
    "methods_and_skills": 25,
    "research_experience": 20,
    "academic_preparation": 15,
    "user_preferences": 5,
}

DEADLINE_PRECISIONS = {"DATE", "DATETIME", "ROLLING", "UNKNOWN"}
DEADLINE_STATUSES = {
    "OPEN",
    "OPEN_UNTIL_FILLED",
    "CLOSED",
    "EXPIRED",
    "UNKNOWN",
    "CONFLICT",
}
DOCTORAL_STATUSES = {"CONFIRMED", "NOT_DOCTORAL", "UNKNOWN", "CONFLICT"}
APPLICATION_STATUSES = {"VERIFIED", "NOT_VERIFIED", "CONFLICT"}
FUNDING_ROUTES = {
    "SALARY",
    "PROJECT_ATTACHED",
    "GUARANTEED_PROGRAM",
    "AUTOMATIC_CONSIDERATION",
    "SEPARATE_APPLICATION",
    "COMPETITIVE",
    "SELF_FUNDED",
    "UNKNOWN",
}
FUNDING_STATUSES = {"VERIFIED", "NOT_VERIFIED", "INELIGIBLE", "CONFLICT"}
COVERAGE_VALUES = {"FULL", "PARTIAL", "NONE", "NOT_APPLICABLE", "UNKNOWN"}
STIPEND_PERIODS = {"YEAR", "MONTH", "WEEK", "HOUR", "TOTAL", "UNKNOWN"}
ELIGIBILITY_STATUSES = {"ELIGIBLE", "INELIGIBLE", "UNKNOWN", "CONFLICT"}
EVIDENCE_FACTS = {
    "OFFICIAL_POSTING",
    "DEADLINE",
    "FUNDING",
    "ELIGIBILITY",
    "APPLICATION",
    "LOCATION",
    "OTHER",
}
EVIDENCE_AUTHORITIES = {"PRIMARY", "AUTHORIZED_ATS", "NATIONAL_PORTAL", "SECONDARY"}
REVIEW_MODES = {"INDEPENDENT_AGENT", "SELF_SECOND_PASS"}
REVIEW_VERDICTS = {"PASS", "HOLD", "FAIL"}
CSV_FIELDS = [
    "record_id",
    "first_seen_date",
    "last_verified_date",
    "last_changed_date",
    "status",
    "is_new_today",
    "score_at_discovery",
    "current_match_score",
    "verification_confidence",
    "eligibility_status",
    "funding_route",
    "funding_summary",
    "title",
    "research_topic",
    "university",
    "department",
    "city",
    "country",
    "supervisor",
    "program_deadline",
    "funding_deadline",
    "effective_action_deadline",
    "deadline_status",
    "short_match_explanation",
    "main_risk",
    "official_posting_url",
    "application_url",
    "funding_url",
    "evidence_urls",
    "profile_version",
    "scoring_version",
]

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref_src",
    "ref_url",
}
FORMULA_PREFIXES = {"=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋", "－", "＠"}


class ContractError(RuntimeError):
    """Raised when a requested state transition violates a tracker contract."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    current = value or utc_now()
    return current.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def emit(value: Any) -> None:
    print(json_dump(value))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ContractError(f"Required file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"Invalid JSON in {path}: {exc}") from exc


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json_dump(value) + "\n")


def normalized_text(value: Any) -> str:
    text_value = "" if value is None else str(value)
    text_value = unicodedata.normalize("NFKC", text_value)
    return " ".join(text_value.split()).casefold()


def display_text(value: Any) -> str:
    text_value = "" if value is None else str(value)
    return " ".join(unicodedata.normalize("NFKC", text_value).split())


def hash_json(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cv_inventory(input_path: Path) -> tuple[list[Path], str | None]:
    if not input_path.exists():
        return [], None
    files = sorted(
        (
            item
            for item in input_path.rglob("*")
            if item.is_file() and item.suffix.casefold() in CV_EXTENSIONS
        ),
        key=lambda item: item.relative_to(input_path).as_posix().casefold(),
    )
    if not files:
        return [], None
    inventory = [
        {
            "path": item.relative_to(input_path).as_posix(),
            "size": item.stat().st_size,
            "sha256": hash_file(item),
        }
        for item in files
    ]
    return files, hash_json(inventory)


def normalize_url(raw_url: str) -> str:
    raw_url = display_text(raw_url)
    require(bool(raw_url), "URL cannot be blank")
    parsed = urllib.parse.urlsplit(raw_url)
    require(parsed.scheme.lower() in {"http", "https"}, f"URL must use http or https: {raw_url}")
    require(bool(parsed.hostname), f"URL has no hostname: {raw_url}")

    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower().rstrip(".")
    port = parsed.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")

    query_pairs = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered.startswith("utm_") or lowered in TRACKING_QUERY_KEYS:
            continue
        query_pairs.append((key, value))
    query_pairs.sort(key=lambda item: (item[0].casefold(), item[1]))
    query = urllib.parse.urlencode(query_pairs, doseq=True)
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def validate_url(raw_url: Any, field: str, *, required: bool = False) -> str | None:
    if raw_url in (None, ""):
        if required:
            raise ContractError(f"{field} is required")
        return None
    require(isinstance(raw_url, str), f"{field} must be a string or null")
    return normalize_url(raw_url)


def parse_iso_deadline(value: str, field: str) -> tuple[str, date | datetime]:
    require(isinstance(value, str) and value.strip(), f"{field} must be a nonblank ISO 8601 string")
    candidate = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        try:
            return "DATE", date.fromisoformat(candidate)
        except ValueError as exc:
            raise ContractError(f"Invalid {field}: {candidate}") from exc
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"Invalid {field}: {candidate}") from exc
    require(parsed.tzinfo is not None, f"{field} datetime must include a UTC offset: {candidate}")
    return "DATETIME", parsed


def parse_timestamp(value: Any, field: str) -> datetime:
    require(isinstance(value, str) and value.strip(), f"{field} must be an offset-bearing timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"Invalid {field}: {value}") from exc
    require(parsed.tzinfo is not None, f"{field} must include a UTC offset")
    return parsed


def load_timezone(name: str):
    if normalized_text(name) in {"utc", "etc/utc", "etc/gmt", "gmt", "z"}:
        return timezone.utc
    require(ZoneInfo is not None, "Python zoneinfo support is required")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ContractError(
            f"Unknown IANA timezone: {name}. On Windows Python, install the tzdata package for named zones"
        ) from exc


def deadline_expired(value: str | None, timezone_name: str, now: datetime | None = None) -> bool:
    if not value:
        return False
    kind, parsed = parse_iso_deadline(value, "effective_action_deadline")
    current = now or utc_now()
    if kind == "DATE":
        local_today = current.astimezone(load_timezone(timezone_name)).date()
        return local_today > parsed
    return current >= parsed.astimezone(timezone.utc)


def deadline_days(value: str | None, timezone_name: str, now: datetime | None = None) -> float | None:
    if not value:
        return None
    kind, parsed = parse_iso_deadline(value, "effective_action_deadline")
    current = now or utc_now()
    if kind == "DATE":
        local_today = current.astimezone(load_timezone(timezone_name)).date()
        return float((parsed - local_today).days)
    return (parsed.astimezone(timezone.utc) - current).total_seconds() / 86400.0


def deadline_instant(value: str, timezone_name: str) -> datetime:
    kind, parsed = parse_iso_deadline(value, "deadline")
    if kind == "DATE":
        return datetime.combine(parsed, time.max, tzinfo=load_timezone(timezone_name)).astimezone(timezone.utc)
    return parsed.astimezone(timezone.utc)


def earliest_deadline(values: Iterable[str | None], timezone_name: str) -> str | None:
    present = [value for value in values if value]
    if not present:
        return None
    return min(present, key=lambda value: deadline_instant(value, timezone_name))


def deadlines_equivalent(left: str, right: str, timezone_name: str) -> bool:
    left_kind, _ = parse_iso_deadline(left, "deadline")
    right_kind, _ = parse_iso_deadline(right, "deadline")
    if left_kind == "DATE" or right_kind == "DATE":
        return left_kind == right_kind and left == right
    return deadline_instant(left, timezone_name) == deadline_instant(right, timezone_name)


def spreadsheet_safe(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    text_value = unicodedata.normalize("NFKC", str(value)).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    stripped = text_value.lstrip()
    if (text_value and text_value[0] in FORMULA_PREFIXES) or (
        stripped and stripped[0] in FORMULA_PREFIXES
    ):
        return "'" + text_value
    return text_value


def markdown_escape(value: Any) -> str:
    escaped = html.escape(display_text(value), quote=True)
    return escaped.replace("\\", "\\\\").replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")


def markdown_url(value: str) -> str:
    return urllib.parse.quote(value, safe=":/?#[]@!$&'*+,;=%")


def local_date_from_timestamp(value: Any, timezone_name: str) -> str:
    if not value:
        return ""
    return parse_timestamp(value, "stored timestamp").astimezone(load_timezone(timezone_name)).date().isoformat()


def workspace_paths(workspace: Path) -> dict[str, Path]:
    root = workspace.expanduser().resolve()
    return {
        "root": root,
        "input": root / "input",
        "backups": root / "backups",
        "reports": root / "reports",
        "logs": root / "logs",
        "config": root / "config.json",
        "profile": root / "profile.json",
        "database": root / "tracker.sqlite3",
        "csv": root / "opportunities.csv",
        "lock": root / ".run.lock",
        "gitignore": root / ".gitignore",
    }


def default_config(countries: list[str], timezone_name: str, daily_time: str) -> dict[str, Any]:
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "countries": countries,
        "timezone": timezone_name,
        "daily_time": daily_time,
        "minimum_match_score": 80,
        "minimum_verification_confidence": 85,
        "scoring_version": "1.0",
        "funding_policy": {
            "accepted_routes": [
                "SALARY",
                "PROJECT_ATTACHED",
                "GUARANTEED_PROGRAM",
            ],
            "fully_funded_required": True,
            "international_fees_required": True,
            "minimum_stipend": None,
            "minimum_stipend_currency": None,
            "minimum_stipend_period": None,
        },
        "search": {
            "closing_soon_days": 14,
            "reverify_active_days": 7,
            "reverify_closing_days": 1,
            "reverify_internal_days": 30,
            "deep_rotation_days": 7,
            "max_evidence_age_hours": 48,
            "max_run_hours": 6,
            "max_backups": 30,
        },
        "preferences": {
            "desired_start_window": None,
            "minimum_application_lead_days": 0,
            "excluded_topics": [],
            "excluded_institutions": [],
        },
        "source_registry": {
            country: {"required_core_sources": [], "local_terms": []} for country in countries
        },
        "privacy": {
            "allow_name_in_queries": False,
            "allow_cv_upload": False,
        },
    }


def default_profile() -> dict[str, Any]:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "confirmed_by_user": False,
        "confirmed_at": None,
        "eligibility": {
            "nationalities": [],
            "residencies": [],
            "work_or_study_rights": [],
            "language_evidence": [],
        },
        "education": [],
        "research_interests": [],
        "methods": [],
        "tools": [],
        "publications_and_projects": [],
        "experience": [],
        "preferences": {
            "desired_start_window": None,
            "excluded_topics": [],
            "excluded_institutions": [],
        },
        "fact_provenance": [],
    }


def validate_daily_time(value: Any) -> str:
    require(isinstance(value, str) and re.fullmatch(r"\d{2}:\d{2}", value) is not None, "daily_time must be HH:MM")
    hour, minute = [int(part) for part in value.split(":")]
    require(0 <= hour <= 23 and 0 <= minute <= 59, "daily_time must be a valid 24-hour time")
    return value


def validate_config(config: Any) -> tuple[dict[str, Any], list[str]]:
    require(isinstance(config, dict), "config.json must contain an object")
    require(config.get("schema_version") == CONFIG_SCHEMA_VERSION, f"config schema_version must be {CONFIG_SCHEMA_VERSION}")
    countries = config.get("countries")
    require(isinstance(countries, list) and countries, "countries must be a nonempty list")
    cleaned_countries: list[str] = []
    seen: set[str] = set()
    for country in countries:
        require(isinstance(country, str) and display_text(country), "every country must be a nonblank string")
        cleaned = display_text(country)
        key = normalized_text(cleaned)
        require(key not in seen, f"duplicate country: {cleaned}")
        seen.add(key)
        cleaned_countries.append(cleaned)
    config["countries"] = cleaned_countries

    timezone_name = config.get("timezone")
    require(isinstance(timezone_name, str) and timezone_name, "timezone is required")
    load_timezone(timezone_name)
    validate_daily_time(config.get("daily_time"))

    minimum_score = config.get("minimum_match_score")
    require(isinstance(minimum_score, (int, float)) and not isinstance(minimum_score, bool), "minimum_match_score must be numeric")
    require(80 <= float(minimum_score) <= 100, "minimum_match_score must be between 80 and 100")
    confidence = config.get("minimum_verification_confidence")
    require(isinstance(confidence, (int, float)) and not isinstance(confidence, bool), "minimum_verification_confidence must be numeric")
    require(0 <= float(confidence) <= 100, "minimum_verification_confidence must be between 0 and 100")
    require(isinstance(config.get("scoring_version"), str) and config["scoring_version"].strip(), "scoring_version is required")

    policy = config.get("funding_policy")
    require(isinstance(policy, dict), "funding_policy must be an object")
    routes = policy.get("accepted_routes")
    require(isinstance(routes, list) and routes, "funding_policy.accepted_routes must be a nonempty list")
    invalid_routes = sorted(set(routes) - FUNDING_ROUTES)
    require(not invalid_routes, f"unknown accepted funding routes: {invalid_routes}")
    require("SELF_FUNDED" not in routes and "UNKNOWN" not in routes, "SELF_FUNDED and UNKNOWN cannot be accepted routes")
    for key in ("fully_funded_required", "international_fees_required"):
        require(isinstance(policy.get(key), bool), f"funding_policy.{key} must be true or false")
    minimum_stipend = policy.get("minimum_stipend")
    minimum_currency = policy.get("minimum_stipend_currency")
    minimum_period = policy.get("minimum_stipend_period")
    if minimum_stipend is None:
        require(minimum_currency is None and minimum_period is None, "minimum stipend currency/period require minimum_stipend")
    else:
        require(
            isinstance(minimum_stipend, (int, float))
            and not isinstance(minimum_stipend, bool)
            and float(minimum_stipend) > 0,
            "funding_policy.minimum_stipend must be a positive number or null",
        )
        require(
            isinstance(minimum_currency, str) and re.fullmatch(r"[A-Z]{3}", minimum_currency) is not None,
            "funding_policy.minimum_stipend_currency must be a three-letter uppercase currency code",
        )
        require(
            minimum_period in STIPEND_PERIODS - {"UNKNOWN"},
            f"funding_policy.minimum_stipend_period must be one of {sorted(STIPEND_PERIODS - {'UNKNOWN'})}",
        )

    search = config.get("search")
    require(isinstance(search, dict), "search must be an object")
    integer_fields = (
        "closing_soon_days",
        "reverify_active_days",
        "reverify_closing_days",
        "reverify_internal_days",
        "deep_rotation_days",
        "max_evidence_age_hours",
        "max_run_hours",
        "max_backups",
    )
    for key in integer_fields:
        require(isinstance(search.get(key), int) and not isinstance(search.get(key), bool) and search[key] >= 0, f"search.{key} must be a nonnegative integer")
    require(search["max_run_hours"] > 0, "search.max_run_hours must be greater than zero")
    require(search["max_evidence_age_hours"] > 0, "search.max_evidence_age_hours must be greater than zero")
    require(search["max_backups"] > 0, "search.max_backups must be greater than zero")

    preferences = config.get("preferences")
    require(isinstance(preferences, dict), "preferences must be an object")
    lead_days = preferences.get("minimum_application_lead_days", 0)
    require(isinstance(lead_days, int) and not isinstance(lead_days, bool) and lead_days >= 0, "preferences.minimum_application_lead_days must be a nonnegative integer")
    registry = config.get("source_registry")
    require(isinstance(registry, dict), "source_registry must be an object")
    privacy = config.get("privacy")
    require(isinstance(privacy, dict), "privacy must be an object")
    require(privacy.get("allow_name_in_queries") is False, "privacy.allow_name_in_queries must remain false")
    require(privacy.get("allow_cv_upload") is False, "privacy.allow_cv_upload must remain false")

    warnings = []
    registry_keys = {normalized_text(key) for key in registry if isinstance(key, str)}
    for country in cleaned_countries:
        if normalized_text(country) not in registry_keys:
            warnings.append(f"source_registry has no entry for {country}")
            continue
        entry = next(
            (value for key, value in registry.items() if normalized_text(key) == normalized_text(country)),
            None,
        )
        require(isinstance(entry, dict), f"source_registry entry for {country} must be an object")
        required_sources = entry.get("required_core_sources")
        local_terms = entry.get("local_terms")
        require(
            isinstance(required_sources, list),
            f"source_registry.{country}.required_core_sources must be a list",
        )
        require(
            isinstance(local_terms, list)
            and all(isinstance(term, str) and display_text(term) for term in local_terms),
            f"source_registry.{country}.local_terms must be a list of nonblank strings",
        )
        for index, source in enumerate(required_sources):
            if isinstance(source, dict):
                name = source.get("name")
                url = source.get("url")
                require(
                    isinstance(name, str) and bool(display_text(name)),
                    f"source_registry.{country}.required_core_sources[{index}].name is required",
                )
                validate_url(
                    url,
                    f"source_registry.{country}.required_core_sources[{index}].url",
                    required=True,
                )
            else:
                raise ContractError(
                    f"source_registry.{country}.required_core_sources[{index}] must be an object with name and canonical URL"
                )
        if not required_sources:
            warnings.append(
                f"source_registry for {country} has no required core sources; runs cannot be COMPLETE"
            )
    return config, warnings


def validate_profile(profile: Any, *, require_confirmed: bool) -> tuple[dict[str, Any], list[str]]:
    require(isinstance(profile, dict), "profile.json must contain an object")
    require(profile.get("schema_version") == PROFILE_SCHEMA_VERSION, f"profile schema_version must be {PROFILE_SCHEMA_VERSION}")
    require(isinstance(profile.get("eligibility"), dict), "profile eligibility must be an object")
    require(isinstance(profile.get("education"), list), "profile education must be a list")
    require(isinstance(profile.get("research_interests"), list), "profile research_interests must be a list")
    require(isinstance(profile.get("methods"), list), "profile methods must be a list")
    require(isinstance(profile.get("tools"), list), "profile tools must be a list")
    warnings = []
    if require_confirmed:
        require(profile.get("confirmed_by_user") is True, "profile has not been confirmed by the user")
        confirmed_at = parse_timestamp(profile.get("confirmed_at"), "profile.confirmed_at")
        require(
            confirmed_at.astimezone(timezone.utc) <= utc_now() + timedelta(minutes=10),
            "profile.confirmed_at is in the future",
        )
        require(bool(profile.get("education")), "confirmed profile must include at least one education record")
        require(bool(profile.get("research_interests")), "confirmed profile must include at least one research interest")
        nationalities = profile["eligibility"].get("nationalities")
        require(isinstance(nationalities, list) and nationalities, "confirmed profile must include user-confirmed nationality eligibility facts")
    else:
        if profile.get("confirmed_by_user") is not True:
            warnings.append("profile is not yet user-confirmed")
    return profile, warnings


def connect_database(path: Path, *, create: bool = False) -> sqlite3.Connection:
    if not path.exists() and not create:
        raise ContractError(f"Tracker database does not exist: {path}")
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    if create:
        connection.execute("PRAGMA journal_mode = WAL")
    ensure_schema(connection)
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > DB_SCHEMA_VERSION:
        raise ContractError(f"Database schema {version} is newer than tracker schema {DB_SCHEMA_VERSION}")
    if version == 1:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(opportunities)").fetchall()
        }
        with connection:
            if "stipend_amount" not in columns:
                connection.execute("ALTER TABLE opportunities ADD COLUMN stipend_amount REAL")
            if "stipend_currency" not in columns:
                connection.execute("ALTER TABLE opportunities ADD COLUMN stipend_currency TEXT")
            if "stipend_period" not in columns:
                connection.execute(
                    "ALTER TABLE opportunities ADD COLUMN stipend_period TEXT NOT NULL DEFAULT 'UNKNOWN'"
                )
            connection.execute("PRAGMA user_version = 2")
        version = 2
    if version == 2:
        run_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(runs)").fetchall()
        }
        with connection:
            if "cv_hash" not in run_columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN cv_hash TEXT NOT NULL DEFAULT ''"
                )
            if "cv_changed" not in run_columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN cv_changed INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute("PRAGMA user_version = 3")
        version = 3
    if version == DB_SCHEMA_VERSION:
        return
    if version != 0:
        raise ContractError(f"No migration path from database schema {version}")
    with connection:
        connection.executescript(
            """
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                profile_hash TEXT NOT NULL,
                cv_hash TEXT NOT NULL,
                scoring_version TEXT NOT NULL,
                countries_json TEXT NOT NULL,
                countries_added_json TEXT NOT NULL,
                countries_removed_json TEXT NOT NULL,
                profile_changed INTEGER NOT NULL,
                cv_changed INTEGER NOT NULL,
                scoring_changed INTEGER NOT NULL,
                coverage_json TEXT,
                notes TEXT,
                report_path TEXT,
                export_path TEXT
            );

            CREATE TABLE opportunities (
                record_id TEXT PRIMARY KEY,
                authority_key TEXT NOT NULL,
                official_id TEXT,
                fingerprint TEXT NOT NULL,
                canonical_url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                research_topic TEXT,
                university TEXT NOT NULL,
                department TEXT,
                city TEXT,
                country TEXT NOT NULL,
                supervisor TEXT,
                doctoral_status TEXT NOT NULL,
                application_status TEXT NOT NULL,
                program_deadline TEXT,
                funding_deadline TEXT,
                effective_action_deadline TEXT,
                deadline_timezone TEXT,
                deadline_precision TEXT NOT NULL,
                deadline_status TEXT NOT NULL,
                funding_route TEXT NOT NULL,
                funding_status TEXT NOT NULL,
                funding_summary TEXT,
                tuition_coverage TEXT NOT NULL,
                stipend_coverage TEXT NOT NULL,
                international_fee_coverage TEXT NOT NULL,
                stipend_amount REAL,
                stipend_currency TEXT,
                stipend_period TEXT NOT NULL,
                eligibility_status TEXT NOT NULL,
                eligibility_summary TEXT,
                verification_confidence REAL,
                score_at_discovery REAL,
                current_match_score REAL,
                score_breakdown_json TEXT,
                short_match_explanation TEXT,
                main_risk TEXT,
                official_posting_url TEXT,
                application_url TEXT,
                funding_url TEXT,
                current_decision TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL,
                in_scope INTEGER NOT NULL,
                ever_published INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_verified_at TEXT,
                last_changed_at TEXT NOT NULL,
                published_at TEXT,
                content_hash TEXT NOT NULL,
                profile_version TEXT NOT NULL,
                scoring_version TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                review_json TEXT,
                rejection_reason TEXT,
                created_run_id TEXT NOT NULL REFERENCES runs(run_id),
                updated_run_id TEXT NOT NULL REFERENCES runs(run_id)
            );

            CREATE UNIQUE INDEX opportunity_official_identity
                ON opportunities(authority_key, official_id)
                WHERE official_id IS NOT NULL AND official_id <> '';
            CREATE INDEX opportunity_fingerprint ON opportunities(fingerprint);
            CREATE INDEX opportunity_country_scope ON opportunities(country, in_scope);
            CREATE INDEX opportunity_due ON opportunities(lifecycle_status, last_verified_at);

            CREATE TABLE aliases (
                alias_url TEXT PRIMARY KEY,
                record_id TEXT NOT NULL REFERENCES opportunities(record_id) ON DELETE CASCADE,
                source_type TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE INDEX alias_record ON aliases(record_id);

            CREATE TABLE evaluations (
                evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT NOT NULL REFERENCES opportunities(record_id) ON DELETE CASCADE,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                evaluated_at TEXT NOT NULL,
                decision TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL,
                match_score REAL,
                verification_confidence REAL,
                profile_version TEXT NOT NULL,
                scoring_version TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                packet_json TEXT NOT NULL,
                reasons_json TEXT NOT NULL
            );

            CREATE TABLE run_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                record_id TEXT REFERENCES opportunities(record_id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            PRAGMA user_version = 3;
            """
        )


def get_metadata(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO metadata(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def validate_workspace(paths: dict[str, Path], *, allow_unconfirmed: bool) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    config = None
    profile = None
    try:
        config, config_warnings = validate_config(read_json(paths["config"]))
        warnings.extend(config_warnings)
    except ContractError as exc:
        errors.append(str(exc))
    try:
        profile, profile_warnings = validate_profile(
            read_json(paths["profile"]), require_confirmed=not allow_unconfirmed
        )
        warnings.extend(profile_warnings)
    except ContractError as exc:
        errors.append(str(exc))

    cv_paths, cv_hash = cv_inventory(paths["input"])
    cv_files = [str(item.resolve()) for item in cv_paths]
    if not cv_files:
        errors.append(f"No CV file found in {paths['input']}")

    integrity = None
    if paths["database"].exists():
        try:
            connection = connect_database(paths["database"])
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            connection.close()
            if integrity.casefold() != "ok":
                errors.append(f"SQLite integrity check failed: {integrity}")
        except (sqlite3.Error, ContractError) as exc:
            errors.append(f"Database validation failed: {exc}")
    else:
        errors.append(f"Tracker database does not exist: {paths['database']}")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "workspace": str(paths["root"]),
        "cv_files": cv_files,
        "cv_hash": cv_hash,
        "config": config,
        "profile": profile,
        "config_hash": hash_json(config) if config is not None else None,
        "profile_hash": hash_json(profile) if profile is not None else None,
        "database_integrity": integrity,
    }


def export_csv(connection: sqlite3.Connection, paths: dict[str, Path], config: dict[str, Any]) -> Path:
    rows = connection.execute(
        """
        SELECT * FROM opportunities
        WHERE ever_published = 1
        ORDER BY first_seen_at DESC,
                 COALESCE(current_match_score, -1) DESC,
                 CASE WHEN effective_action_deadline IS NULL OR effective_action_deadline = '' THEN 1 ELSE 0 END,
                 effective_action_deadline ASC
        """
    ).fetchall()
    local_today = utc_now().astimezone(load_timezone(config["timezone"])).date().isoformat()
    descriptor, temporary_name = tempfile.mkstemp(prefix=".opportunities.", suffix=".csv.tmp", dir=paths["root"])
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                evidence = json.loads(row["evidence_json"] or "[]")
                evidence_urls = []
                for item in evidence:
                    url = item.get("url") if isinstance(item, dict) else None
                    if url and url not in evidence_urls:
                        evidence_urls.append(url)
                mapped = {
                    "record_id": row["record_id"],
                    "first_seen_date": local_date_from_timestamp(row["first_seen_at"], config["timezone"]),
                    "last_verified_date": local_date_from_timestamp(row["last_verified_at"], config["timezone"]),
                    "last_changed_date": local_date_from_timestamp(row["last_changed_at"], config["timezone"]),
                    "status": row["lifecycle_status"],
                    "is_new_today": local_date_from_timestamp(row["first_seen_at"], config["timezone"]) == local_today,
                    "score_at_discovery": row["score_at_discovery"],
                    "current_match_score": row["current_match_score"],
                    "verification_confidence": row["verification_confidence"],
                    "eligibility_status": row["eligibility_status"],
                    "funding_route": row["funding_route"],
                    "funding_summary": row["funding_summary"],
                    "title": row["title"],
                    "research_topic": row["research_topic"],
                    "university": row["university"],
                    "department": row["department"],
                    "city": row["city"],
                    "country": row["country"],
                    "supervisor": row["supervisor"],
                    "program_deadline": row["program_deadline"],
                    "funding_deadline": row["funding_deadline"],
                    "effective_action_deadline": row["effective_action_deadline"],
                    "deadline_status": row["deadline_status"],
                    "short_match_explanation": row["short_match_explanation"],
                    "main_risk": row["main_risk"],
                    "official_posting_url": row["official_posting_url"],
                    "application_url": row["application_url"],
                    "funding_url": row["funding_url"],
                    "evidence_urls": " | ".join(evidence_urls),
                    "profile_version": row["profile_version"],
                    "scoring_version": row["scoring_version"],
                }
                writer.writerow({key: spreadsheet_safe(value) for key, value in mapped.items()})
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temporary, paths["csv"])
        except PermissionError as exc:
            raise ContractError(
                f"Could not replace {paths['csv']}; close it in Excel or another program, then run export"
            ) from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return paths["csv"]


def command_init(args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    root = paths["root"]
    if root.exists():
        require(root.is_dir(), f"Workspace path is not a directory: {root}")
        require(not any(root.iterdir()), f"Initialization refuses nonempty workspace: {root}")
    countries = [display_text(value) for value in args.country]
    require(all(countries), "Every --country value must be nonblank")
    validate_daily_time(args.daily_time)
    load_timezone(args.timezone)
    config = default_config(countries, args.timezone, args.daily_time)
    validate_config(config)

    root.mkdir(parents=True, exist_ok=True)
    for key in ("input", "backups", "reports", "logs"):
        paths[key].mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths["config"], config)
    atomic_write_json(paths["profile"], default_profile())
    atomic_write_text(
        paths["gitignore"],
        "# Private applicant workspace: ignore everything by default.\n*\n!.gitignore\n",
    )
    connection = connect_database(paths["database"], create=True)
    export_csv(connection, paths, config)
    connection.close()
    return {
        "ok": True,
        "workspace": str(root),
        "next_steps": [
            f"Place the CV in {paths['input']}",
            f"Complete and user-confirm {paths['profile']}",
            "Run validate before the baseline search",
        ],
        "tracker_version": TRACKER_VERSION,
    }


def command_validate(args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    result = validate_workspace(paths, allow_unconfirmed=args.allow_unconfirmed)
    if not result["ok"]:
        raise ContractError("; ".join(result["errors"]))
    result.pop("profile", None)
    result.pop("config", None)
    result["tracker_version"] = TRACKER_VERSION
    return result


def country_map(countries: Iterable[str]) -> dict[str, str]:
    return {normalized_text(country): display_text(country) for country in countries}


def load_runtime(
    paths: dict[str, Path],
) -> tuple[dict[str, Any], dict[str, Any], str, str, str]:
    validation = validate_workspace(paths, allow_unconfirmed=False)
    if not validation["ok"]:
        raise ContractError("; ".join(validation["errors"]))
    config = validation["config"]
    profile = validation["profile"]
    assert isinstance(config, dict) and isinstance(profile, dict)
    return (
        config,
        profile,
        str(validation["config_hash"]),
        str(validation["profile_hash"]),
        str(validation["cv_hash"]),
    )


def acquire_run_lock(paths: dict[str, Path], run_id: str, max_run_hours: int) -> dict[str, Any] | None:
    lock_path = paths["lock"]
    stale_record = None
    if lock_path.exists():
        existing = None
        try:
            existing = read_json(lock_path)
        except ContractError:
            existing = None
        created_at = None
        if isinstance(existing, dict):
            try:
                created_at = parse_timestamp(existing.get("created_at"), "lock.created_at")
            except ContractError:
                created_at = None
        if created_at is None:
            created_at = datetime.fromtimestamp(lock_path.stat().st_mtime, tz=timezone.utc)
        age = utc_now() - created_at.astimezone(timezone.utc)
        if age <= timedelta(hours=max_run_hours):
            owner = existing.get("run_id") if isinstance(existing, dict) else "unknown"
            raise ContractError(f"Another run lock is active for {owner}; refusing overlapping writes")
        stale_record = existing if isinstance(existing, dict) else {"run_id": None}
        archive_name = f"stale-lock-{utc_now().strftime('%Y%m%dT%H%M%SZ')}.json"
        paths["logs"].mkdir(parents=True, exist_ok=True)
        os.replace(lock_path, paths["logs"] / archive_name)

    payload = {
        "run_id": run_id,
        "created_at": iso_utc(),
        "pid": os.getpid(),
        "tracker_version": TRACKER_VERSION,
    }
    descriptor = None
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            handle.write(json_dump(payload) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ContractError("Another run acquired the workspace lock") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return stale_record


def release_run_lock(paths: dict[str, Path], run_id: str) -> None:
    lock_path = paths["lock"]
    if not lock_path.exists():
        return
    payload = read_json(lock_path)
    require(isinstance(payload, dict) and payload.get("run_id") == run_id, "Run lock belongs to a different run")
    lock_path.unlink()


def require_run_lock(paths: dict[str, Path], run_id: str) -> None:
    require(paths["lock"].exists(), f"Run {run_id} has no active workspace lock")
    payload = read_json(paths["lock"])
    require(
        isinstance(payload, dict) and payload.get("run_id") == run_id,
        f"Workspace lock does not belong to run {run_id}",
    )


def recover_finished_run_lock(paths: dict[str, Path]) -> str | None:
    if not paths["lock"].exists() or not paths["database"].exists():
        return None
    try:
        payload = read_json(paths["lock"])
    except ContractError:
        return None
    if not isinstance(payload, dict) or not payload.get("run_id"):
        return None
    connection = connect_database(paths["database"])
    try:
        row = connection.execute(
            "SELECT status FROM runs WHERE run_id = ?", (payload["run_id"],)
        ).fetchone()
    finally:
        connection.close()
    if row is None or row["status"] == "RUNNING":
        return None
    paths["logs"].mkdir(parents=True, exist_ok=True)
    archive = paths["logs"] / (
        f"finished-run-lock-{payload['run_id']}-{utc_now().strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    os.replace(paths["lock"], archive)
    return str(archive)


def backup_database(connection: sqlite3.Connection, paths: dict[str, Path], max_backups: int) -> Path:
    paths["backups"].mkdir(parents=True, exist_ok=True)
    destination = paths["backups"] / f"tracker-{utc_now().strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
    target = sqlite3.connect(destination)
    try:
        connection.backup(target)
    finally:
        target.close()
    backups = sorted(paths["backups"].glob("tracker-*.sqlite3"), key=lambda item: item.stat().st_mtime, reverse=True)
    for old in backups[max_backups:]:
        old.unlink(missing_ok=True)
    return destination


def require_running_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    require(row is not None, f"Unknown run_id: {run_id}")
    require(row["status"] == "RUNNING", f"Run {run_id} is not RUNNING; status is {row['status']}")
    return row


def assert_run_snapshot(
    run: sqlite3.Row,
    config_hash: str,
    profile_hash: str,
    cv_hash: str,
    config: dict[str, Any],
) -> None:
    mismatches = []
    if run["config_hash"] != config_hash:
        mismatches.append("config.json changed")
    if run["profile_hash"] != profile_hash:
        mismatches.append("profile.json changed")
    if run["cv_hash"] != cv_hash:
        mismatches.append("CV input changed")
    if run["scoring_version"] != config["scoring_version"]:
        mismatches.append("scoring_version changed")
    require(
        not mismatches,
        "Run snapshot drift detected ("
        + ", ".join(mismatches)
        + "); abort this run and start a new baseline-aware run",
    )


def add_event(
    connection: sqlite3.Connection,
    run_id: str,
    record_id: str | None,
    event_type: str,
    details: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        "INSERT INTO run_events(run_id, record_id, event_type, details_json, created_at) VALUES(?, ?, ?, ?, ?)",
        (run_id, record_id, event_type, json.dumps(details or {}, ensure_ascii=False, sort_keys=True), iso_utc()),
    )


def mark_scope(connection: sqlite3.Connection, configured_countries: list[str]) -> None:
    allowed = set(country_map(configured_countries))
    rows = connection.execute("SELECT record_id, country, in_scope, lifecycle_status FROM opportunities").fetchall()
    with connection:
        for row in rows:
            in_scope = normalized_text(row["country"]) in allowed
            if in_scope == bool(row["in_scope"]):
                continue
            lifecycle = row["lifecycle_status"]
            if not in_scope:
                lifecycle = "OUT_OF_SCOPE"
            connection.execute(
                "UPDATE opportunities SET in_scope = ?, lifecycle_status = ?, last_changed_at = ? WHERE record_id = ?",
                (int(in_scope), lifecycle, iso_utc(), row["record_id"]),
            )


def command_run_start(args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    config, profile, config_hash, profile_hash, cv_hash = load_runtime(paths)
    recovered_lock = recover_finished_run_lock(paths)
    run_id = f"run-{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    stale = acquire_run_lock(paths, run_id, int(config["search"]["max_run_hours"]))
    connection = None
    try:
        connection = connect_database(paths["database"])
        backup = backup_database(connection, paths, int(config["search"]["max_backups"]))
        if isinstance(stale, dict) and stale.get("run_id"):
            with connection:
                connection.execute(
                    "UPDATE runs SET status = 'ABORTED', finished_at = ?, notes = COALESCE(notes, '') || ? WHERE run_id = ? AND status = 'RUNNING'",
                    (iso_utc(), "\nAutomatically aborted after stale lock recovery.", stale["run_id"]),
                )

        previous_countries_raw = get_metadata(connection, "last_completed_countries")
        previous_countries = json.loads(previous_countries_raw) if previous_countries_raw else []
        previous_map = country_map(previous_countries)
        current_map = country_map(config["countries"])
        added = [current_map[key] for key in current_map.keys() - previous_map.keys()]
        removed = [previous_map[key] for key in previous_map.keys() - current_map.keys()]
        if not previous_countries_raw:
            added = list(config["countries"])
            removed = []

        previous_profile_hash = get_metadata(connection, "last_completed_profile_hash")
        previous_cv_hash = get_metadata(connection, "last_completed_cv_hash")
        previous_scoring_version = get_metadata(connection, "last_completed_scoring_version")
        profile_changed = previous_profile_hash is not None and previous_profile_hash != profile_hash
        cv_changed = previous_cv_hash is not None and previous_cv_hash != cv_hash
        scoring_changed = previous_scoring_version is not None and previous_scoring_version != config["scoring_version"]
        require(
            not cv_changed or profile_changed,
            "CV input changed since the last complete run but profile.json was not updated and reconfirmed; rebuild or reconfirm the profile before monitoring",
        )
        if cv_changed:
            previous_run_id = get_metadata(connection, "last_completed_run_id")
            previous_run = (
                connection.execute(
                    "SELECT finished_at FROM runs WHERE run_id = ?", (previous_run_id,)
                ).fetchone()
                if previous_run_id
                else None
            )
            require(
                previous_run is not None and previous_run["finished_at"],
                "Cannot verify CV/profile reconfirmation chronology against the prior complete run",
            )
            confirmed_at = parse_timestamp(
                profile.get("confirmed_at"), "profile.confirmed_at"
            )
            prior_finished_at = parse_timestamp(
                previous_run["finished_at"], "previous run finished_at"
            )
            require(
                confirmed_at.astimezone(timezone.utc)
                > prior_finished_at.astimezone(timezone.utc),
                "CV input changed, but profile.confirmed_at is not later than the prior complete run; re-extract and explicitly reconfirm the profile",
            )

        mark_scope(connection, config["countries"])
        with connection:
            connection.execute(
                """
                INSERT INTO runs(
                    run_id, started_at, status, config_hash, profile_hash, cv_hash, scoring_version,
                    countries_json, countries_added_json, countries_removed_json,
                    profile_changed, cv_changed, scoring_changed
                ) VALUES(?, ?, 'RUNNING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    iso_utc(),
                    config_hash,
                    profile_hash,
                    cv_hash,
                    config["scoring_version"],
                    json.dumps(config["countries"], ensure_ascii=False),
                    json.dumps(added, ensure_ascii=False),
                    json.dumps(removed, ensure_ascii=False),
                    int(profile_changed),
                    int(cv_changed),
                    int(scoring_changed),
                ),
            )
        return {
            "ok": True,
            "run_id": run_id,
            "countries": config["countries"],
            "countries_added": added,
            "countries_removed": removed,
            "profile_changed": profile_changed,
            "cv_changed": cv_changed,
            "scoring_changed": scoring_changed,
            "config_hash": config_hash,
            "profile_version": profile_hash[:12],
            "cv_version": cv_hash[:12],
            "backup": str(backup),
            "recovered_finished_lock": recovered_lock,
        }
    except Exception:
        try:
            release_run_lock(paths, run_id)
        except Exception:
            pass
        raise
    finally:
        if connection is not None:
            connection.close()


def record_due_reason(
    row: sqlite3.Row,
    config: dict[str, Any],
    profile_hash: str,
    scoring_version: str,
    *,
    force_profile: bool = False,
    force_scoring: bool = False,
    added_countries: set[str] | None = None,
) -> str | None:
    terminal = {"CLOSED", "EXPIRED", "WITHDRAWN"}
    if not row["in_scope"] or row["lifecycle_status"] in terminal:
        return None
    if force_profile or row["profile_version"] != profile_hash[:12]:
        return "profile_changed"
    if force_scoring or row["scoring_version"] != scoring_version:
        return "scoring_changed"
    if added_countries and normalized_text(row["country"]) in added_countries:
        return "country_added"
    if row["last_verified_at"] is None:
        return "never_verified"

    last_verified = parse_timestamp(row["last_verified_at"], "last_verified_at")
    age_days = (utc_now() - last_verified.astimezone(timezone.utc)).total_seconds() / 86400.0
    days = deadline_days(
        row["effective_action_deadline"], row["deadline_timezone"] or config["timezone"]
    )
    search = config["search"]
    if row["deadline_status"] == "OPEN_UNTIL_FILLED":
        interval = search["reverify_active_days"]
        return "rolling_reverification" if age_days >= interval else None
    if days is not None and days <= search["closing_soon_days"]:
        interval = search["reverify_closing_days"]
        return "closing_soon_reverification" if age_days >= interval else None
    if row["current_decision"] in {"HOLD", "UNDER_THRESHOLD", "REJECT"}:
        interval = search["reverify_internal_days"]
        return "internal_reverification" if age_days >= interval else None
    interval = search["reverify_active_days"]
    return "active_reverification" if age_days >= interval else None


def command_due(args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    config, _profile, config_hash, profile_hash, cv_hash = load_runtime(paths)
    connection = connect_database(paths["database"])
    try:
        run = require_running_run(connection, args.run_id)
        require_run_lock(paths, args.run_id)
        assert_run_snapshot(run, config_hash, profile_hash, cv_hash, config)
        added = {normalized_text(value) for value in json.loads(run["countries_added_json"])}
        due = []
        for row in connection.execute("SELECT * FROM opportunities ORDER BY last_verified_at ASC").fetchall():
            reason = record_due_reason(
                row,
                config,
                profile_hash,
                config["scoring_version"],
                force_profile=bool(run["profile_changed"]),
                force_scoring=bool(run["scoring_changed"]),
                added_countries=added,
            )
            if reason:
                due.append(
                    {
                        "record_id": row["record_id"],
                        "title": row["title"],
                        "university": row["university"],
                        "country": row["country"],
                        "official_posting_url": row["official_posting_url"],
                        "deadline": row["effective_action_deadline"],
                        "current_decision": row["current_decision"],
                        "lifecycle_status": row["lifecycle_status"],
                        "last_verified_at": row["last_verified_at"],
                        "content_hash": row["content_hash"],
                        "reason": reason,
                    }
                )
        return {"ok": True, "run_id": args.run_id, "count": len(due), "records": due}
    finally:
        connection.close()


def candidate_fingerprint(values: dict[str, Any]) -> str:
    material = {
        "official_id": normalized_text(values.get("official_id")),
        "university": normalized_text(values.get("university")),
        "title": normalized_text(values.get("title")),
        "research_topic": normalized_text(values.get("research_topic")),
        "department": normalized_text(values.get("department")),
        "city": normalized_text(values.get("city")),
        "country": normalized_text(values.get("country")),
        "supervisor": normalized_text(values.get("supervisor")),
        "cycle": normalized_text(
            values.get("effective_action_deadline")
            or values.get("program_deadline")
            or values.get("funding_deadline")
            or values.get("start_cycle")
        ),
    }
    return hash_json(material)


def authority_key(values: dict[str, Any], canonical_url: str) -> str:
    explicit = display_text(values.get("authority_key"))
    if explicit:
        return normalized_text(explicit)
    host = urllib.parse.urlsplit(canonical_url).hostname
    university = normalized_text(values.get("university"))
    return f"{university}|{normalized_text(host)}" if university else normalized_text(host)


def find_identity_signals(
    connection: sqlite3.Connection,
    *,
    record_id: str | None,
    official_id: str | None,
    authority: str | None,
    urls: Iterable[str],
    fingerprint: str | None,
) -> tuple[list[str], list[str]]:
    strong_matches: set[str] = set()
    if record_id:
        row = connection.execute("SELECT record_id FROM opportunities WHERE record_id = ?", (record_id,)).fetchone()
        require(row is not None, f"record_id does not exist: {record_id}")
        strong_matches.add(str(row["record_id"]))
    if official_id and authority:
        row = connection.execute(
            "SELECT record_id FROM opportunities WHERE authority_key = ? AND official_id = ?",
            (authority, official_id),
        ).fetchone()
        if row:
            strong_matches.add(str(row["record_id"]))
    for url in urls:
        row = connection.execute("SELECT record_id FROM opportunities WHERE canonical_url = ?", (url,)).fetchone()
        if row:
            strong_matches.add(str(row["record_id"]))
        row = connection.execute("SELECT record_id FROM aliases WHERE alias_url = ?", (url,)).fetchone()
        if row:
            strong_matches.add(str(row["record_id"]))
    fingerprint_matches: set[str] = set()
    if fingerprint:
        rows = connection.execute("SELECT record_id FROM opportunities WHERE fingerprint = ?", (fingerprint,)).fetchall()
        fingerprint_matches.update(str(row["record_id"]) for row in rows)
    require(
        len(strong_matches) <= 1,
        f"Strong identity signals conflict across records: {sorted(strong_matches)}",
    )
    return sorted(strong_matches), sorted(fingerprint_matches)


def validate_existing_record_update(
    connection: sqlite3.Connection,
    existing: sqlite3.Row,
    packet: dict[str, Any],
    fingerprint: str,
    identity_urls: list[str],
    *,
    explicit_record_id: bool,
) -> None:
    if explicit_record_id:
        require(
            packet["expected_prior_content_hash"] == existing["content_hash"],
            "expected_prior_content_hash does not match the current canonical record; run lookup/due again before updating",
        )
    require(
        normalized_text(packet["university"]) == normalized_text(existing["university"]),
        "candidate update cannot change the canonical university identity",
    )
    require(
        normalized_text(packet["country"]) == normalized_text(existing["country"]),
        "candidate update cannot change the canonical country identity",
    )

    existing_official_id = display_text(existing["official_id"])
    packet_official_id = display_text(packet["official_id"])
    if existing_official_id:
        require(
            normalized_text(packet_official_id) == normalized_text(existing_official_id),
            "candidate update cannot remove or replace the canonical official_id",
        )
        return

    known_urls = {str(existing["canonical_url"])}
    known_urls.update(
        str(row["alias_url"])
        for row in connection.execute(
            "SELECT alias_url FROM aliases WHERE record_id = ?", (existing["record_id"],)
        ).fetchall()
    )
    require(
        bool(known_urls.intersection(identity_urls))
        or fingerprint == existing["fingerprint"],
        "candidate update lacks a matching canonical URL, alias, official identity, or fingerprint",
    )


def command_lookup(args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    config, _profile, _config_hash, profile_hash, _cv_hash = load_runtime(paths)
    connection = connect_database(paths["database"])
    try:
        urls = [normalize_url(args.url)] if args.url else []
        values = {
            "official_id": args.official_id,
            "title": args.title,
            "university": args.university,
            "research_topic": args.research_topic,
            "department": args.department,
            "city": args.city,
            "country": args.country,
            "supervisor": args.supervisor,
            "effective_action_deadline": args.deadline,
        }
        fingerprint = None
        if args.title and args.university:
            fingerprint = candidate_fingerprint(values)
        authority = None
        if args.official_id:
            if urls:
                authority = authority_key(values, urls[0])
            elif args.university:
                authority = normalized_text(args.university)
            else:
                raise ContractError("--official-id requires --url or --university")
        matches, fingerprint_matches = find_identity_signals(
            connection,
            record_id=None,
            official_id=args.official_id,
            authority=authority,
            urls=urls,
            fingerprint=fingerprint,
        )
        if not matches:
            possible = []
            for possible_id in fingerprint_matches:
                possible_row = connection.execute(
                    "SELECT record_id, title, university, country, official_posting_url FROM opportunities WHERE record_id = ?",
                    (possible_id,),
                ).fetchone()
                if possible_row:
                    possible.append(dict(possible_row))
            return {"ok": True, "found": False, "possible_duplicates": possible}
        row = connection.execute("SELECT * FROM opportunities WHERE record_id = ?", (matches[0],)).fetchone()
        assert row is not None
        reason = record_due_reason(row, config, profile_hash, config["scoring_version"])
        return {
            "ok": True,
            "found": True,
            "record_id": row["record_id"],
            "title": row["title"],
            "university": row["university"],
            "country": row["country"],
            "current_decision": row["current_decision"],
            "lifecycle_status": row["lifecycle_status"],
            "last_seen_at": row["last_seen_at"],
            "last_verified_at": row["last_verified_at"],
            "content_hash": row["content_hash"],
            "recheck_due": reason is not None,
            "recheck_reason": reason,
            "possible_duplicate_record_ids": [
                value for value in fingerprint_matches if value != row["record_id"]
            ],
        }
    finally:
        connection.close()


def upsert_alias(
    connection: sqlite3.Connection,
    record_id: str,
    url: str,
    source_type: str,
    observed_at: str,
) -> None:
    existing = connection.execute("SELECT record_id FROM aliases WHERE alias_url = ?", (url,)).fetchone()
    if existing and existing["record_id"] != record_id:
        raise ContractError(f"Alias URL already belongs to another record: {url}")
    connection.execute(
        """
        INSERT INTO aliases(alias_url, record_id, source_type, first_seen_at, last_seen_at)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(alias_url) DO UPDATE SET
            source_type = excluded.source_type,
            last_seen_at = excluded.last_seen_at
        """,
        (url, record_id, source_type, observed_at, observed_at),
    )


def command_touch(args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    config, _profile, config_hash, profile_hash, cv_hash = load_runtime(paths)
    connection = connect_database(paths["database"])
    observed = iso_utc()
    try:
        run = require_running_run(connection, args.run_id)
        require_run_lock(paths, args.run_id)
        assert_run_snapshot(run, config_hash, profile_hash, cv_hash, config)
        row = connection.execute("SELECT record_id FROM opportunities WHERE record_id = ?", (args.record_id,)).fetchone()
        require(row is not None, f"Unknown record_id: {args.record_id}")
        url = normalize_url(args.url) if args.url else None
        with connection:
            connection.execute(
                "UPDATE opportunities SET last_seen_at = ?, updated_run_id = ? WHERE record_id = ?",
                (observed, args.run_id, args.record_id),
            )
            if url:
                upsert_alias(connection, args.record_id, url, "DISCOVERY", observed)
            add_event(connection, args.run_id, args.record_id, "SEEN_UNCHANGED", {"url": url})
        return {"ok": True, "record_id": args.record_id, "last_seen_at": observed}
    finally:
        connection.close()


def enum_value(packet: dict[str, Any], key: str, allowed: set[str]) -> str:
    value = packet.get(key)
    require(isinstance(value, str) and value in allowed, f"{key} must be one of {sorted(allowed)}")
    return value


def optional_text(packet: dict[str, Any], key: str) -> str | None:
    value = packet.get(key)
    if value is None:
        return None
    require(isinstance(value, str), f"{key} must be a string or null")
    cleaned = display_text(value)
    return cleaned or None


def required_text(packet: dict[str, Any], key: str) -> str:
    value = optional_text(packet, key)
    require(value is not None, f"{key} is required")
    return value


def validate_score(score: Any) -> tuple[dict[str, Any] | None, float | None]:
    if score is None:
        return None, None
    require(isinstance(score, dict), "score must be an object or null")
    require(set(score) == set(SCORE_COMPONENTS), f"score must contain exactly {sorted(SCORE_COMPONENTS)}")
    cleaned: dict[str, Any] = {}
    total = 0.0
    for key, expected_max in SCORE_COMPONENTS.items():
        component = score.get(key)
        require(isinstance(component, dict), f"score.{key} must be an object")
        points = component.get("points")
        maximum = component.get("max")
        evidence = component.get("evidence")
        require(isinstance(points, (int, float)) and not isinstance(points, bool), f"score.{key}.points must be numeric")
        require(maximum == expected_max, f"score.{key}.max must be {expected_max}")
        require(0 <= float(points) <= expected_max, f"score.{key}.points must be between 0 and {expected_max}")
        require(isinstance(evidence, str) and display_text(evidence), f"score.{key}.evidence is required")
        cleaned[key] = {"points": float(points), "max": expected_max, "evidence": display_text(evidence)}
        total += float(points)
    return cleaned, round(total, 2)


def validate_evidence(evidence: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    require(isinstance(evidence, list) and evidence, "evidence must be a nonempty list")
    cleaned: list[dict[str, Any]] = []
    max_age = timedelta(hours=int(config["search"]["max_evidence_age_hours"]))
    current = utc_now()
    for index, item in enumerate(evidence):
        require(isinstance(item, dict), f"evidence[{index}] must be an object")
        fact = item.get("fact")
        authority = item.get("authority")
        require(fact in EVIDENCE_FACTS, f"evidence[{index}].fact must be one of {sorted(EVIDENCE_FACTS)}")
        require(authority in EVIDENCE_AUTHORITIES, f"evidence[{index}].authority must be one of {sorted(EVIDENCE_AUTHORITIES)}")
        url = validate_url(item.get("url"), f"evidence[{index}].url", required=True)
        checked_at = parse_timestamp(item.get("checked_at"), f"evidence[{index}].checked_at")
        require(checked_at.astimezone(timezone.utc) <= current + timedelta(minutes=10), f"evidence[{index}].checked_at is in the future")
        require(current - checked_at.astimezone(timezone.utc) <= max_age, f"evidence[{index}] is older than the configured evidence limit")
        summary = item.get("summary")
        require(isinstance(summary, str) and display_text(summary), f"evidence[{index}].summary is required")
        cleaned.append(
            {
                "fact": fact,
                "url": url,
                "authority": authority,
                "checked_at": checked_at.isoformat(),
                "summary": display_text(summary),
            }
        )
    return cleaned


def candidate_review_subject_hash(
    packet: dict[str, Any], review_context: dict[str, str]
) -> str:
    material = copy.deepcopy(packet)
    material.pop("review", None)
    material.pop("content_hash", None)
    if isinstance(material.get("discovery_urls"), list):
        material["discovery_urls"] = sorted(material["discovery_urls"])
    if isinstance(material.get("evidence"), list):
        material["evidence"] = sorted(
            material["evidence"],
            key=lambda item: (
                item.get("fact", ""),
                item.get("url", ""),
                item.get("authority", ""),
                item.get("checked_at", ""),
            ),
        )
    return hash_json({"candidate": material, "runtime": review_context})


def validate_review(
    review: Any,
    config: dict[str, Any],
    expected_subject_hash: str,
) -> dict[str, Any] | None:
    if review is None:
        return None
    require(isinstance(review, dict), "review must be an object or null")
    mode = review.get("mode")
    verdict = review.get("verdict")
    require(mode in REVIEW_MODES, f"review.mode must be one of {sorted(REVIEW_MODES)}")
    require(verdict in REVIEW_VERDICTS, f"review.verdict must be one of {sorted(REVIEW_VERDICTS)}")
    reviewer_id = review.get("reviewer_id")
    require(
        isinstance(reviewer_id, str) and display_text(reviewer_id),
        "review.reviewer_id is required",
    )
    subject_hash = review.get("subject_hash")
    require(
        isinstance(subject_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", subject_hash) is not None,
        "review.subject_hash must be a lowercase SHA-256 digest",
    )
    require(
        subject_hash == expected_subject_hash,
        "critical review is not bound to this normalized candidate, evidence, and runtime snapshot; regenerate the review subject hash and review again",
    )
    reviewed_at = parse_timestamp(review.get("reviewed_at"), "review.reviewed_at")
    current = utc_now()
    require(reviewed_at.astimezone(timezone.utc) <= current + timedelta(minutes=10), "review.reviewed_at is in the future")
    max_age = timedelta(hours=int(config["search"]["max_evidence_age_hours"]))
    require(current - reviewed_at.astimezone(timezone.utc) <= max_age, "critical review is older than the configured evidence limit")
    notes = review.get("notes")
    require(isinstance(notes, str) and display_text(notes), "review.notes is required")
    return {
        "mode": mode,
        "verdict": verdict,
        "reviewer_id": display_text(reviewer_id),
        "subject_hash": subject_hash,
        "reviewed_at": reviewed_at.isoformat(),
        "notes": display_text(notes),
    }


def validate_candidate_packet(
    packet: Any,
    config: dict[str, Any],
    review_context: dict[str, str],
) -> tuple[dict[str, Any], float | None, str]:
    require(isinstance(packet, dict), "candidate packet must contain an object")
    cleaned: dict[str, Any] = {}
    cleaned["record_id"] = optional_text(packet, "record_id")
    cleaned["expected_prior_content_hash"] = optional_text(
        packet, "expected_prior_content_hash"
    )
    if cleaned["record_id"]:
        require(
            cleaned["expected_prior_content_hash"] is not None
            and re.fullmatch(r"[0-9a-f]{64}", cleaned["expected_prior_content_hash"])
            is not None,
            "expected_prior_content_hash must be the current lowercase SHA-256 content hash when record_id is supplied",
        )
    else:
        require(
            cleaned["expected_prior_content_hash"] is None,
            "expected_prior_content_hash is only valid with record_id",
        )
    cleaned["official_id"] = optional_text(packet, "official_id")
    for key in ("title", "university", "country"):
        cleaned[key] = required_text(packet, key)
    for key in ("research_topic", "department", "city", "supervisor"):
        cleaned[key] = optional_text(packet, key)

    cleaned["doctoral_status"] = enum_value(packet, "doctoral_status", DOCTORAL_STATUSES)
    cleaned["application_status"] = enum_value(packet, "application_status", APPLICATION_STATUSES)

    for key in ("program_deadline", "funding_deadline", "effective_action_deadline"):
        value = optional_text(packet, key)
        if value:
            parse_iso_deadline(value, key)
        cleaned[key] = value
    cleaned["deadline_timezone"] = optional_text(packet, "deadline_timezone")
    if cleaned["deadline_timezone"]:
        load_timezone(cleaned["deadline_timezone"])
    cleaned["deadline_precision"] = enum_value(packet, "deadline_precision", DEADLINE_PRECISIONS)
    cleaned["deadline_status"] = enum_value(packet, "deadline_status", DEADLINE_STATUSES)

    cleaned["funding_route"] = enum_value(packet, "funding_route", FUNDING_ROUTES)
    cleaned["funding_status"] = enum_value(packet, "funding_status", FUNDING_STATUSES)
    cleaned["funding_summary"] = optional_text(packet, "funding_summary")
    cleaned["tuition_coverage"] = enum_value(packet, "tuition_coverage", COVERAGE_VALUES)
    cleaned["stipend_coverage"] = enum_value(packet, "stipend_coverage", COVERAGE_VALUES)
    cleaned["international_fee_coverage"] = enum_value(packet, "international_fee_coverage", COVERAGE_VALUES)
    stipend_amount = packet.get("stipend_amount")
    if stipend_amount is not None:
        require(
            isinstance(stipend_amount, (int, float))
            and not isinstance(stipend_amount, bool)
            and float(stipend_amount) >= 0,
            "stipend_amount must be a nonnegative number or null",
        )
        stipend_amount = float(stipend_amount)
    cleaned["stipend_amount"] = stipend_amount
    stipend_currency = optional_text(packet, "stipend_currency")
    if stipend_currency is not None:
        stipend_currency = stipend_currency.upper()
        require(re.fullmatch(r"[A-Z]{3}", stipend_currency) is not None, "stipend_currency must be a three-letter currency code")
    cleaned["stipend_currency"] = stipend_currency
    cleaned["stipend_period"] = enum_value(packet, "stipend_period", STIPEND_PERIODS)
    if stipend_amount is not None:
        require(stipend_currency is not None, "stipend_currency is required when stipend_amount is supplied")
        require(cleaned["stipend_period"] != "UNKNOWN", "stipend_period is required when stipend_amount is supplied")
    cleaned["eligibility_status"] = enum_value(packet, "eligibility_status", ELIGIBILITY_STATUSES)
    cleaned["eligibility_summary"] = optional_text(packet, "eligibility_summary")

    confidence = packet.get("verification_confidence")
    if confidence is not None:
        require(isinstance(confidence, (int, float)) and not isinstance(confidence, bool), "verification_confidence must be numeric or null")
        require(0 <= float(confidence) <= 100, "verification_confidence must be between 0 and 100")
        confidence = float(confidence)
    cleaned["verification_confidence"] = confidence
    cleaned_score, total = validate_score(packet.get("score"))
    cleaned["score"] = cleaned_score
    cleaned["short_match_explanation"] = optional_text(packet, "short_match_explanation")
    cleaned["main_risk"] = optional_text(packet, "main_risk")

    cleaned["official_posting_url"] = validate_url(packet.get("official_posting_url"), "official_posting_url")
    cleaned["application_url"] = validate_url(packet.get("application_url"), "application_url")
    cleaned["funding_url"] = validate_url(packet.get("funding_url"), "funding_url")
    discovery = packet.get("discovery_urls", [])
    require(isinstance(discovery, list), "discovery_urls must be a list")
    cleaned_discovery = []
    for index, url in enumerate(discovery):
        normalized = validate_url(url, f"discovery_urls[{index}]", required=True)
        if normalized not in cleaned_discovery:
            cleaned_discovery.append(normalized)
    cleaned["discovery_urls"] = cleaned_discovery
    require(cleaned["official_posting_url"] or cleaned_discovery, "candidate requires an official or discovery URL")

    cleaned["evidence"] = validate_evidence(packet.get("evidence"), config)
    review_raw = packet.get("review")
    cleaned["rejection_reason"] = optional_text(packet, "rejection_reason")

    supplied_hash = optional_text(packet, "content_hash")
    require(supplied_hash is None, "content_hash is tracker-computed and must be null or omitted")
    cleaned["content_hash"] = None

    duplicate_review = packet.get("duplicate_review")
    if duplicate_review is not None:
        require(isinstance(duplicate_review, dict), "duplicate_review must be an object or null")
        require(duplicate_review.get("verdict") == "DISTINCT", "duplicate_review.verdict must be DISTINCT")
        record_ids = duplicate_review.get("record_ids")
        require(
            isinstance(record_ids, list)
            and record_ids
            and all(isinstance(value, str) and display_text(value) for value in record_ids),
            "duplicate_review.record_ids must be a nonempty list of record IDs",
        )
        reason = duplicate_review.get("reason")
        require(isinstance(reason, str) and display_text(reason), "duplicate_review.reason is required")
        reviewed_at = parse_timestamp(duplicate_review.get("reviewed_at"), "duplicate_review.reviewed_at")
        require(
            reviewed_at.astimezone(timezone.utc) <= utc_now() + timedelta(minutes=10),
            "duplicate_review.reviewed_at is in the future",
        )
        require(
            utc_now() - reviewed_at.astimezone(timezone.utc)
            <= timedelta(hours=int(config["search"]["max_evidence_age_hours"])),
            "duplicate_review is older than the configured evidence limit",
        )
        cleaned["duplicate_review"] = {
            "verdict": "DISTINCT",
            "record_ids": sorted(set(record_ids)),
            "reason": display_text(reason),
            "reviewed_at": reviewed_at.isoformat(),
        }
    else:
        cleaned["duplicate_review"] = None
    subject_hash = candidate_review_subject_hash(cleaned, review_context)
    cleaned["review"] = validate_review(review_raw, config, subject_hash)
    return cleaned, total, subject_hash


def material_packet_hash(packet: dict[str, Any]) -> str:
    material = copy.deepcopy(packet)
    material.pop("record_id", None)
    material.pop("expected_prior_content_hash", None)
    material.pop("content_hash", None)
    review = material.get("review")
    if isinstance(review, dict):
        review.pop("reviewed_at", None)
        review.pop("subject_hash", None)
    for item in material.get("evidence", []):
        if isinstance(item, dict):
            item.pop("checked_at", None)
    if isinstance(material.get("discovery_urls"), list):
        material["discovery_urls"] = sorted(material["discovery_urls"])
    if isinstance(material.get("evidence"), list):
        material["evidence"] = sorted(
            material["evidence"], key=lambda item: (item.get("fact", ""), item.get("url", ""))
        )
    return hash_json(material)


def command_review_subject(args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    config, _profile, config_hash, profile_hash, cv_hash = load_runtime(paths)
    packet_raw = read_json(Path(args.file).expanduser().resolve())
    require(isinstance(packet_raw, dict), "candidate packet must contain an object")
    packet_without_review = copy.deepcopy(packet_raw)
    packet_without_review["review"] = None
    review_context = {
        "config_hash": config_hash,
        "profile_hash": profile_hash,
        "cv_hash": cv_hash,
    }
    _packet, _score_total, subject_hash = validate_candidate_packet(
        packet_without_review, config, review_context
    )
    return {
        "ok": True,
        "subject_hash": subject_hash,
        "profile_version": profile_hash[:12],
        "cv_version": cv_hash[:12],
        "instruction": "Review this exact normalized candidate/evidence snapshot, then copy subject_hash into review.subject_hash.",
    }


def authoritative_fact_present(evidence: list[dict[str, Any]], fact: str) -> bool:
    return any(
        item["fact"] == fact and item["authority"] in {"PRIMARY", "AUTHORIZED_ATS"}
        for item in evidence
    )


def derive_decision(
    packet: dict[str, Any],
    score_total: float | None,
    config: dict[str, Any],
) -> tuple[str, str, list[str]]:
    reasons: list[str] = []
    configured = set(country_map(config["countries"]))
    in_scope = normalized_text(packet["country"]) in configured
    status = packet["deadline_status"]
    deadline_zone = packet["deadline_timezone"] or config["timezone"]
    supplied_effective = packet["effective_action_deadline"]
    derived_effective = earliest_deadline(
        [packet["program_deadline"], packet["funding_deadline"]], deadline_zone
    )
    if status == "OPEN_UNTIL_FILLED":
        if packet["deadline_precision"] != "ROLLING":
            reasons.append("open-until-filled status requires ROLLING deadline precision")
        if derived_effective or supplied_effective:
            reasons.append("open-until-filled status conflicts with a fixed component/effective deadline")
        effective_deadline = None
    else:
        if not derived_effective:
            reasons.append("no component programme/position or funding deadline is established")
            effective_deadline = supplied_effective
        else:
            if not supplied_effective or not deadlines_equivalent(
                supplied_effective, derived_effective, deadline_zone
            ):
                reasons.append("effective action deadline does not equal the earliest component deadline")
            effective_deadline = derived_effective
            packet["effective_action_deadline"] = derived_effective
            expected_precision, _ = parse_iso_deadline(derived_effective, "effective_action_deadline")
            if packet["deadline_precision"] != expected_precision:
                reasons.append(
                    f"deadline precision {packet['deadline_precision']} does not match derived {expected_precision}"
                )
                packet["deadline_precision"] = expected_precision
    if packet["funding_route"] == "SEPARATE_APPLICATION":
        if not packet["program_deadline"] or not packet["funding_deadline"]:
            reasons.append("separate funding requires both programme and funding deadlines")
    if effective_deadline and deadline_expired(effective_deadline, deadline_zone):
        status = "EXPIRED"
        packet["deadline_status"] = "EXPIRED"

    if not in_scope:
        return "REJECT", "OUT_OF_SCOPE", ["host country is outside the current configuration"]
    if packet["doctoral_status"] == "NOT_DOCTORAL":
        if authoritative_fact_present(packet["evidence"], "OFFICIAL_POSTING"):
            return "REJECT", "REJECTED", ["authoritative source does not describe a doctoral opportunity"]
        reasons.append("negative doctoral classification lacks authoritative posting evidence")
    if status in {"CLOSED", "EXPIRED"}:
        if authoritative_fact_present(packet["evidence"], "DEADLINE"):
            return "REJECT", status, [f"authoritative deadline status is {status}"]
        reasons.append(f"{status.lower()} classification lacks authoritative deadline evidence")
    if packet["funding_status"] == "INELIGIBLE" or packet["funding_route"] == "SELF_FUNDED":
        if authoritative_fact_present(packet["evidence"], "FUNDING"):
            return "REJECT", "REJECTED", ["authoritative funding evidence does not satisfy the configured policy"]
        reasons.append("negative funding classification lacks authoritative funding evidence")
    if packet["eligibility_status"] == "INELIGIBLE":
        if authoritative_fact_present(packet["evidence"], "ELIGIBILITY"):
            return "REJECT", "INELIGIBLE", ["confirmed profile fails an authoritative eligibility requirement"]
        reasons.append("ineligibility classification lacks authoritative eligibility evidence")
    if packet.get("review") and packet["review"]["verdict"] == "FAIL":
        return "REJECT", "REJECTED", ["critical review failed"]
    if packet["funding_route"] not in set(config["funding_policy"]["accepted_routes"]) and packet["funding_route"] != "UNKNOWN":
        if authoritative_fact_present(packet["evidence"], "FUNDING"):
            return "REJECT", "REJECTED", [f"authoritative funding route {packet['funding_route']} is not accepted by configuration"]
        reasons.append(
            f"unaccepted funding route {packet['funding_route']} lacks authoritative funding evidence"
        )

    unknown_checks = [
        (packet["doctoral_status"] in {"UNKNOWN", "CONFLICT"}, "doctoral status is not confirmed"),
        (packet["application_status"] != "VERIFIED", "application path is not verified"),
        (status in {"UNKNOWN", "CONFLICT"}, "deadline is unknown or conflicting"),
        (packet["funding_status"] != "VERIFIED", "funding is not verified"),
        (packet["funding_route"] == "UNKNOWN", "funding route is unknown"),
        (packet["eligibility_status"] in {"UNKNOWN", "CONFLICT"}, "eligibility is unknown or conflicting"),
    ]
    reasons.extend(message for failed, message in unknown_checks if failed)
    if status == "OPEN" and not effective_deadline:
        reasons.append("open candidate has no effective action deadline")
    if packet["deadline_precision"] == "UNKNOWN":
        reasons.append("deadline precision is unknown")
    if not packet["official_posting_url"]:
        reasons.append("official posting URL is missing")
    if not packet["application_url"]:
        reasons.append("application URL is missing")

    required_facts = {"OFFICIAL_POSTING", "DEADLINE", "FUNDING", "ELIGIBILITY", "APPLICATION"}
    for fact in sorted(required_facts):
        if not authoritative_fact_present(packet["evidence"], fact):
            reasons.append(f"authoritative {fact.lower()} evidence is missing")

    policy = config["funding_policy"]
    accepted_full = {"FULL", "NOT_APPLICABLE"}
    if policy["fully_funded_required"]:
        if packet["tuition_coverage"] not in accepted_full:
            reasons.append("full tuition coverage is not established")
        if packet["stipend_coverage"] != "FULL":
            reasons.append("full stipend or salary coverage is not established")
    if policy["international_fees_required"] and packet["international_fee_coverage"] not in accepted_full:
        reasons.append("international fee coverage is not established")
    minimum_stipend = policy.get("minimum_stipend")
    if minimum_stipend is not None:
        if packet["stipend_amount"] is None:
            reasons.append("stipend amount is missing despite the configured minimum")
        elif packet["stipend_currency"] != policy["minimum_stipend_currency"]:
            reasons.append("stipend currency does not match the configured minimum currency")
        elif packet["stipend_period"] != policy["minimum_stipend_period"]:
            reasons.append("stipend period does not match the configured minimum period")
        elif packet["stipend_amount"] < float(minimum_stipend):
            if authoritative_fact_present(packet["evidence"], "FUNDING"):
                return "REJECT", "REJECTED", ["authoritative stipend amount is below the configured minimum"]
            reasons.append("apparent stipend is below the configured minimum, but authoritative funding evidence is missing")

    lead_days = int(config["preferences"].get("minimum_application_lead_days", 0))
    remaining = deadline_days(effective_deadline, deadline_zone)
    if remaining is not None and remaining < lead_days:
        if authoritative_fact_present(packet["evidence"], "DEADLINE"):
            return "REJECT", "REJECTED", [f"authoritative deadline has less than the configured {lead_days}-day lead time"]
        reasons.append("apparent lead time is too short, but authoritative deadline evidence is missing")

    if reasons:
        return "HOLD", "HOLD", reasons
    if packet["verification_confidence"] is None:
        return "HOLD", "HOLD", ["verification confidence is missing"]
    if packet["verification_confidence"] < float(config["minimum_verification_confidence"]):
        return "HOLD", "HOLD", ["verification confidence is below the configured minimum"]
    if score_total is None:
        return "HOLD", "HOLD", ["fit score is missing after hard gates passed"]
    if score_total < float(config["minimum_match_score"]):
        return "UNDER_THRESHOLD", "BELOW_CURRENT_THRESHOLD", ["match score is below the reporting threshold"]

    review = packet["review"]
    if review is None:
        return "HOLD", "HOLD", ["critical review is missing"]
    if review["verdict"] == "HOLD":
        return "HOLD", "HOLD", ["critical review returned HOLD"]
    if review["verdict"] != "PASS":
        return "REJECT", "REJECTED", ["critical review did not pass"]
    if not packet["short_match_explanation"]:
        return "HOLD", "HOLD", ["short match explanation is missing"]
    if not packet["main_risk"]:
        return "HOLD", "HOLD", ["main risk is missing"]

    if status == "OPEN_UNTIL_FILLED":
        lifecycle = "OPEN_UNTIL_FILLED"
    else:
        remaining = deadline_days(effective_deadline, deadline_zone)
        lifecycle = (
            "CLOSING_SOON"
            if remaining is not None and remaining <= int(config["search"]["closing_soon_days"])
            else "ACTIVE"
        )
    return "PUBLISH", lifecycle, []


def command_candidate_upsert(args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    config, _profile, config_hash, profile_hash, cv_hash = load_runtime(paths)
    preflight = connect_database(paths["database"])
    try:
        run = require_running_run(preflight, args.run_id)
        require_run_lock(paths, args.run_id)
        assert_run_snapshot(run, config_hash, profile_hash, cv_hash, config)
    finally:
        preflight.close()
    packet_raw = read_json(Path(args.file).expanduser().resolve())
    review_context = {
        "config_hash": config_hash,
        "profile_hash": profile_hash,
        "cv_hash": cv_hash,
    }
    packet, score_total, _subject_hash = validate_candidate_packet(
        packet_raw, config, review_context
    )
    decision, lifecycle, reasons = derive_decision(packet, score_total, config)
    content_hash = material_packet_hash(packet)
    now_value = iso_utc()
    canonical_url = packet["official_posting_url"] or packet["discovery_urls"][0]
    assert canonical_url is not None
    authority = authority_key(packet, canonical_url)
    fingerprint = candidate_fingerprint(packet)
    identity_urls = [canonical_url, *packet["discovery_urls"]]

    connection = connect_database(paths["database"])
    try:
        (
            current_config,
            _current_profile,
            current_config_hash,
            current_profile_hash,
            current_cv_hash,
        ) = load_runtime(paths)
        run = require_running_run(connection, args.run_id)
        require_run_lock(paths, args.run_id)
        assert_run_snapshot(
            run,
            current_config_hash,
            current_profile_hash,
            current_cv_hash,
            current_config,
        )
        matches, fingerprint_matches = find_identity_signals(
            connection,
            record_id=packet["record_id"],
            official_id=packet["official_id"],
            authority=authority,
            urls=identity_urls,
            fingerprint=fingerprint,
        )
        if not matches and fingerprint_matches:
            review = packet.get("duplicate_review")
            require(
                isinstance(review, dict)
                and set(fingerprint_matches).issubset(set(review.get("record_ids", []))),
                "Potential duplicate fingerprint matches "
                + ", ".join(fingerprint_matches)
                + "; review them and supply duplicate_review or use the matching record_id",
            )
        existing = (
            connection.execute("SELECT * FROM opportunities WHERE record_id = ?", (matches[0],)).fetchone()
            if matches
            else None
        )
        if existing is not None:
            validate_existing_record_update(
                connection,
                existing,
                packet,
                fingerprint,
                identity_urls,
                explicit_record_id=bool(packet["record_id"]),
            )
        record_id = str(existing["record_id"]) if existing else f"phd-{uuid.uuid4().hex[:20]}"
        was_published = bool(existing["ever_published"]) if existing else False
        ever_published = was_published or decision == "PUBLISH"
        first_seen = str(existing["first_seen_at"]) if existing else now_value
        published_at = str(existing["published_at"]) if existing and existing["published_at"] else None
        if decision == "PUBLISH" and not published_at:
            published_at = now_value
        score_at_discovery = existing["score_at_discovery"] if existing else score_total
        if score_at_discovery is None and score_total is not None:
            score_at_discovery = score_total

        rejection_reason = packet["rejection_reason"]
        if reasons:
            derived = "; ".join(reasons)
            rejection_reason = f"{rejection_reason}; {derived}" if rejection_reason else derived
        changed = existing is None
        if existing is not None:
            changed = any(
                [
                    existing["content_hash"] != content_hash,
                    existing["current_decision"] != decision,
                    existing["lifecycle_status"] != lifecycle,
                    existing["profile_version"] != profile_hash[:12],
                    existing["scoring_version"] != config["scoring_version"],
                    existing["canonical_url"] != canonical_url,
                ]
            )
        last_changed = now_value if changed or existing is None else str(existing["last_changed_at"])

        row_data = {
            "record_id": record_id,
            "authority_key": authority,
            "official_id": packet["official_id"],
            "fingerprint": fingerprint,
            "canonical_url": canonical_url,
            "title": packet["title"],
            "research_topic": packet["research_topic"],
            "university": packet["university"],
            "department": packet["department"],
            "city": packet["city"],
            "country": packet["country"],
            "supervisor": packet["supervisor"],
            "doctoral_status": packet["doctoral_status"],
            "application_status": packet["application_status"],
            "program_deadline": packet["program_deadline"],
            "funding_deadline": packet["funding_deadline"],
            "effective_action_deadline": packet["effective_action_deadline"],
            "deadline_timezone": packet["deadline_timezone"],
            "deadline_precision": packet["deadline_precision"],
            "deadline_status": packet["deadline_status"],
            "funding_route": packet["funding_route"],
            "funding_status": packet["funding_status"],
            "funding_summary": packet["funding_summary"],
            "tuition_coverage": packet["tuition_coverage"],
            "stipend_coverage": packet["stipend_coverage"],
            "international_fee_coverage": packet["international_fee_coverage"],
            "stipend_amount": packet["stipend_amount"],
            "stipend_currency": packet["stipend_currency"],
            "stipend_period": packet["stipend_period"],
            "eligibility_status": packet["eligibility_status"],
            "eligibility_summary": packet["eligibility_summary"],
            "verification_confidence": packet["verification_confidence"],
            "score_at_discovery": score_at_discovery,
            "current_match_score": score_total,
            "score_breakdown_json": json.dumps(packet["score"], ensure_ascii=False, sort_keys=True) if packet["score"] else None,
            "short_match_explanation": packet["short_match_explanation"],
            "main_risk": packet["main_risk"],
            "official_posting_url": packet["official_posting_url"],
            "application_url": packet["application_url"],
            "funding_url": packet["funding_url"],
            "current_decision": decision,
            "lifecycle_status": lifecycle,
            "in_scope": int(normalized_text(packet["country"]) in set(country_map(config["countries"]))),
            "ever_published": int(ever_published),
            "first_seen_at": first_seen,
            "last_seen_at": now_value,
            "last_verified_at": now_value,
            "last_changed_at": last_changed,
            "published_at": published_at,
            "content_hash": content_hash,
            "profile_version": profile_hash[:12],
            "scoring_version": config["scoring_version"],
            "evidence_json": json.dumps(packet["evidence"], ensure_ascii=False, sort_keys=True),
            "review_json": json.dumps(packet["review"], ensure_ascii=False, sort_keys=True) if packet["review"] else None,
            "rejection_reason": rejection_reason,
            "created_run_id": str(existing["created_run_id"]) if existing else args.run_id,
            "updated_run_id": args.run_id,
        }

        with connection:
            if existing is None:
                columns = list(row_data)
                placeholders = ", ".join("?" for _ in columns)
                connection.execute(
                    f"INSERT INTO opportunities({', '.join(columns)}) VALUES({placeholders})",
                    [row_data[column] for column in columns],
                )
            else:
                old_canonical = str(existing["canonical_url"])
                update_columns = [key for key in row_data if key not in {"record_id", "first_seen_at", "created_run_id"}]
                assignments = ", ".join(f"{column} = ?" for column in update_columns)
                connection.execute(
                    f"UPDATE opportunities SET {assignments} WHERE record_id = ?",
                    [row_data[column] for column in update_columns] + [record_id],
                )
                upsert_alias(connection, record_id, old_canonical, "HISTORICAL", now_value)

            if packet["official_posting_url"]:
                upsert_alias(connection, record_id, packet["official_posting_url"], "OFFICIAL", now_value)
            for url in packet["discovery_urls"]:
                upsert_alias(connection, record_id, url, "DISCOVERY", now_value)

            connection.execute(
                """
                INSERT INTO evaluations(
                    record_id, run_id, evaluated_at, decision, lifecycle_status, match_score,
                    verification_confidence, profile_version, scoring_version, content_hash,
                    packet_json, reasons_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    args.run_id,
                    now_value,
                    decision,
                    lifecycle,
                    score_total,
                    packet["verification_confidence"],
                    profile_hash[:12],
                    config["scoring_version"],
                    content_hash,
                    json.dumps(packet, ensure_ascii=False, sort_keys=True),
                    json.dumps(reasons, ensure_ascii=False),
                ),
            )
            if decision == "PUBLISH" and not was_published:
                event_type = "NEW_PUBLISHED"
            elif existing is None:
                event_type = "NEW_INTERNAL"
            elif changed:
                event_type = "UPDATED_PUBLISHED" if was_published else "UPDATED_INTERNAL"
            else:
                event_type = "VERIFIED_UNCHANGED"
            add_event(
                connection,
                args.run_id,
                record_id,
                event_type,
                {"decision": decision, "lifecycle_status": lifecycle, "reasons": reasons},
            )
        return {
            "ok": True,
            "record_id": record_id,
            "event": event_type,
            "decision": decision,
            "lifecycle_status": lifecycle,
            "visible_in_csv": ever_published,
            "current_match_score": score_total,
            "verification_confidence": packet["verification_confidence"],
            "reasons": reasons,
            "content_hash": content_hash,
            "possible_duplicate_record_ids": [
                value for value in fingerprint_matches if value != record_id
            ],
        }
    finally:
        connection.close()


def registry_for_country(config: dict[str, Any], country: str) -> dict[str, Any]:
    registry = config.get("source_registry", {})
    for key, value in registry.items():
        if normalized_text(key) == normalized_text(country) and isinstance(value, dict):
            return value
    return {}


def normalize_coverage(raw: Any, config: dict[str, Any]) -> tuple[dict[str, Any], str]:
    require(isinstance(raw, dict), "coverage packet must contain an object")
    supplied = raw.get("countries")
    require(isinstance(supplied, dict), "coverage.countries must be an object")
    supplied_map = {normalized_text(key): value for key, value in supplied.items() if isinstance(key, str)}
    normalized: dict[str, Any] = {"countries": {}}
    current = utc_now()
    max_age = timedelta(hours=int(config["search"]["max_evidence_age_hours"]))

    for country in config["countries"]:
        entry = supplied_map.get(normalized_text(country))
        if not isinstance(entry, dict):
            normalized["countries"][country] = {
                "status": "FAILED",
                "notes": "Configured country was omitted from coverage packet.",
                "sources": [],
            }
            continue
        status = entry.get("status")
        require(status in {"COMPLETE", "PARTIAL", "FAILED"}, f"coverage status for {country} is invalid")
        notes = entry.get("notes", "")
        require(isinstance(notes, str), f"coverage notes for {country} must be a string")
        sources = entry.get("sources")
        require(isinstance(sources, list), f"coverage sources for {country} must be a list")
        cleaned_sources = []
        for index, source in enumerate(sources):
            require(isinstance(source, dict), f"coverage source {country}[{index}] must be an object")
            name = source.get("name")
            source_url = validate_url(source.get("url"), f"coverage source {country}[{index}].url", required=True)
            source_class = source.get("class")
            source_status = source.get("status")
            checked_at = parse_timestamp(source.get("checked_at"), f"coverage source {country}[{index}].checked_at")
            require(
                checked_at.astimezone(timezone.utc) <= current + timedelta(minutes=10),
                f"coverage source {country}[{index}].checked_at is in the future",
            )
            require(
                current - checked_at.astimezone(timezone.utc) <= max_age,
                f"coverage source {country}[{index}] is older than the configured evidence limit",
            )
            candidates_seen = source.get("candidates_seen")
            note = source.get("note", "")
            require(isinstance(name, str) and display_text(name), f"coverage source {country}[{index}].name is required")
            require(source_class in {"OFFICIAL", "AUTHORIZED_ATS", "NATIONAL_PORTAL", "AGGREGATOR", "SEARCH"}, f"coverage source {country}[{index}].class is invalid")
            require(source_status in {"OK", "PARTIAL", "FAILED"}, f"coverage source {country}[{index}].status is invalid")
            require(isinstance(candidates_seen, int) and not isinstance(candidates_seen, bool) and candidates_seen >= 0, f"coverage source {country}[{index}].candidates_seen must be a nonnegative integer")
            require(isinstance(note, str), f"coverage source {country}[{index}].note must be a string")
            cleaned_sources.append(
                {
                    "name": display_text(name),
                    "url": source_url,
                    "class": source_class,
                    "status": source_status,
                    "checked_at": checked_at.isoformat(),
                    "candidates_seen": candidates_seen,
                    "note": display_text(note),
                }
            )

        if status == "COMPLETE" and not cleaned_sources:
            status = "FAILED"
            notes = (
                display_text(notes)
                + " Coverage downgraded because no source was recorded."
            ).strip()
        elif status == "COMPLETE" and any(source["status"] != "OK" for source in cleaned_sources):
            status = "PARTIAL"
            notes = (display_text(notes) + " Coverage downgraded because a listed source was not OK.").strip()

        required_sources = registry_for_country(config, country).get("required_core_sources", [])
        require(isinstance(required_sources, list), f"source_registry required_core_sources for {country} must be a list")
        if not required_sources:
            if status != "FAILED":
                status = "PARTIAL" if cleaned_sources else "FAILED"
            notes = (
                display_text(notes)
                + " No required core sources are configured; COMPLETE coverage is not permitted."
            ).strip()
        observed_urls = {source["url"] for source in cleaned_sources if source["status"] == "OK"}
        missing_required = []
        for required_source in required_sources:
            if isinstance(required_source, dict):
                label = display_text(required_source.get("name") or required_source.get("url"))
                required_url = required_source.get("url")
                matched = normalize_url(required_url) in observed_urls
            else:
                raise ContractError(f"Invalid required core source for {country}")
            if not matched:
                missing_required.append(label)
        if missing_required:
            if status != "FAILED":
                status = "PARTIAL" if cleaned_sources else "FAILED"
            notes = (
                display_text(notes)
                + f" Missing successful required core sources: {', '.join(missing_required)}."
            ).strip()

        normalized["countries"][country] = {
            "status": status,
            "notes": display_text(notes),
            "sources": cleaned_sources,
        }

    statuses = [entry["status"] for entry in normalized["countries"].values()]
    if statuses and all(status == "COMPLETE" for status in statuses):
        overall = "COMPLETE"
    elif statuses and all(status == "FAILED" for status in statuses):
        overall = "FAILED"
    else:
        overall = "PARTIAL"
    return normalized, overall


def refresh_lifecycles(
    connection: sqlite3.Connection,
    config: dict[str, Any],
    run_id: str,
) -> None:
    rows = connection.execute("SELECT * FROM opportunities").fetchall()
    configured = set(country_map(config["countries"]))
    for row in rows:
        new_lifecycle = str(row["lifecycle_status"])
        new_deadline_status = str(row["deadline_status"])
        in_scope = normalized_text(row["country"]) in configured
        if not in_scope:
            new_lifecycle = "OUT_OF_SCOPE"
        elif row["lifecycle_status"] not in {"CLOSED", "WITHDRAWN"} and deadline_expired(
            row["effective_action_deadline"], row["deadline_timezone"] or config["timezone"]
        ):
            new_lifecycle = "EXPIRED"
            new_deadline_status = "EXPIRED"
        elif row["current_decision"] == "PUBLISH":
            if row["deadline_status"] == "OPEN_UNTIL_FILLED":
                new_lifecycle = "OPEN_UNTIL_FILLED"
            else:
                remaining = deadline_days(
                    row["effective_action_deadline"],
                    row["deadline_timezone"] or config["timezone"],
                )
                new_lifecycle = (
                    "CLOSING_SOON"
                    if remaining is not None and remaining <= int(config["search"]["closing_soon_days"])
                    else "ACTIVE"
                )
        changed = (
            new_lifecycle != row["lifecycle_status"]
            or new_deadline_status != row["deadline_status"]
            or int(in_scope) != row["in_scope"]
        )
        if changed:
            connection.execute(
                """
                UPDATE opportunities
                SET lifecycle_status = ?, deadline_status = ?, in_scope = ?,
                    last_changed_at = ?, updated_run_id = ?
                WHERE record_id = ?
                """,
                (new_lifecycle, new_deadline_status, int(in_scope), iso_utc(), run_id, row["record_id"]),
            )
            add_event(
                connection,
                run_id,
                row["record_id"],
                "UPDATED_PUBLISHED" if row["ever_published"] else "UPDATED_INTERNAL",
                {"lifecycle_status": new_lifecycle, "deadline_status": new_deadline_status},
            )


def unique_event_records(connection: sqlite3.Connection, run_id: str, event_type: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT o.* FROM opportunities o
        JOIN (
            SELECT record_id, MAX(event_id) AS last_event
            FROM run_events
            WHERE run_id = ? AND event_type = ? AND record_id IS NOT NULL
            GROUP BY record_id
        ) e ON e.record_id = o.record_id
        ORDER BY COALESCE(o.current_match_score, -1) DESC, o.effective_action_deadline ASC
        """,
        (run_id, event_type),
    ).fetchall()


def candidate_report_table(rows: list[sqlite3.Row]) -> list[str]:
    if not rows:
        return []
    lines = [
        "| Score | Opportunity | University / location | Deadline | Funding | Why it matches | Main risk | Direct links |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        official = row["official_posting_url"]
        application = row["application_url"]
        links = []
        if official:
            links.append(f"[Official]({markdown_url(official)})")
        if application:
            links.append(f"[Apply]({markdown_url(application)})")
        location = ", ".join(value for value in [row["university"], row["city"], row["country"]] if value)
        lines.append(
            "| {score} | {title} | {location} | {deadline} | {funding} | {why} | {risk} | {links} |".format(
                score=spreadsheet_safe(row["current_match_score"]),
                title=markdown_escape(row["title"]),
                location=markdown_escape(location),
                deadline=markdown_escape(row["effective_action_deadline"] or row["deadline_status"]),
                funding=markdown_escape(f"{row['funding_route']}: {row['funding_summary'] or ''}"),
                why=markdown_escape(row["short_match_explanation"] or ""),
                risk=markdown_escape(row["main_risk"] or ""),
                links=" · ".join(links),
            )
        )
    return lines


def generate_report(
    connection: sqlite3.Connection,
    paths: dict[str, Path],
    config: dict[str, Any],
    run_id: str,
    coverage: dict[str, Any],
    overall_status: str,
) -> Path:
    require_existing_run(connection, run_id)
    local_now = utc_now().astimezone(load_timezone(config["timezone"]))
    report_path = paths["reports"] / f"{local_now.date().isoformat()}.md"
    new_rows = unique_event_records(connection, run_id, "NEW_PUBLISHED")
    updated_rows = unique_event_records(connection, run_id, "UPDATED_PUBLISHED")
    new_ids = {row["record_id"] for row in new_rows}
    updated_rows = [row for row in updated_rows if row["record_id"] not in new_ids]
    closing_rows = connection.execute(
        """
        SELECT * FROM opportunities
        WHERE ever_published = 1 AND in_scope = 1 AND lifecycle_status = 'CLOSING_SOON'
        ORDER BY effective_action_deadline ASC
        """
    ).fetchall()
    decision_counts = {
        row["decision"]: int(row["count"])
        for row in connection.execute(
            "SELECT decision, COUNT(*) AS count FROM evaluations WHERE run_id = ? GROUP BY decision",
            (run_id,),
        ).fetchall()
    }

    lines = [
        f"# Funded PhD monitor — {local_now.date().isoformat()}",
        "",
        f"- Run: `{run_id}`",
        f"- Local completion time: `{local_now.replace(microsecond=0).isoformat()}`",
        f"- Overall coverage: **{overall_status}**",
        f"- New verified matches scoring at least {config['minimum_match_score']}: **{len(new_rows)}**",
        "",
        "## Country coverage",
        "",
        "| Country | Status | Sources checked | Notes |",
        "|---|---|---:|---|",
    ]
    for country, entry in coverage.get("countries", {}).items():
        lines.append(
            f"| {markdown_escape(country)} | {entry.get('status', 'FAILED')} | {len(entry.get('sources', []))} | {markdown_escape(entry.get('notes', ''))} |"
        )

    lines.extend(["", "## New verified matches", ""])
    if new_rows:
        lines.extend(candidate_report_table(new_rows))
    elif overall_status == "COMPLETE":
        lines.append(f"No newly verified opportunities scoring {config['minimum_match_score']} or higher were found after complete documented coverage.")
    else:
        lines.append("No new publishable matches were established, but coverage was incomplete; this is not evidence that no opportunities exist.")

    lines.extend(["", "## Material updates", ""])
    if updated_rows:
        lines.extend(candidate_report_table(updated_rows))
    else:
        lines.append("No material changes to previously published opportunities were recorded.")

    lines.extend(["", "## Closing soon", ""])
    if closing_rows:
        lines.extend(candidate_report_table(list(closing_rows)))
    else:
        lines.append("No previously published in-scope opportunity is inside the configured closing-soon window.")

    lines.extend(
        [
            "",
            "## Internal screening counts",
            "",
            f"- Published evaluations: {decision_counts.get('PUBLISH', 0)}",
            f"- Held for missing/conflicting evidence: {decision_counts.get('HOLD', 0)}",
            f"- Below threshold: {decision_counts.get('UNDER_THRESHOLD', 0)}",
            f"- Rejected by hard gate: {decision_counts.get('REJECT', 0)}",
            "",
            "## Source failures and limitations",
            "",
        ]
    )
    limitations = []
    for country, entry in coverage.get("countries", {}).items():
        if entry.get("status") != "COMPLETE":
            limitations.append(f"- **{markdown_escape(country)}**: {entry.get('status')} — {markdown_escape(entry.get('notes', 'No note supplied.'))}")
        for source in entry.get("sources", []):
            if source.get("status") != "OK":
                limitations.append(
                    f"  - {markdown_escape(source.get('name'))}: {source.get('status')} — {markdown_escape(source.get('note', ''))}"
                )
    if limitations:
        lines.extend(limitations)
    else:
        lines.append("No source failure was recorded in the declared coverage plan.")

    lines.extend(
        [
            "",
            "## Files",
            "",
            f"- Cumulative CSV: `{paths['csv']}`",
            f"- Canonical SQLite ledger: `{paths['database']}`",
            "",
            "This report documents the sources searched; it does not claim exhaustive coverage of the internet.",
            "",
        ]
    )
    atomic_write_text(report_path, "\n".join(lines))
    return report_path


def require_existing_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    require(row is not None, f"Unknown run_id: {run_id}")
    return row


def command_run_finish(args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    config, _profile, config_hash, profile_hash, cv_hash = load_runtime(paths)
    coverage_raw = read_json(Path(args.coverage).expanduser().resolve())
    coverage, overall = normalize_coverage(coverage_raw, config)
    connection = connect_database(paths["database"])
    export_error = None
    try:
        run = require_running_run(connection, args.run_id)
        require_run_lock(paths, args.run_id)
        assert_run_snapshot(run, config_hash, profile_hash, cv_hash, config)
        with connection:
            refresh_lifecycles(connection, config, args.run_id)

        try:
            export_path = export_csv(connection, paths, config)
        except ContractError as exc:
            export_error = str(exc)
            if overall == "COMPLETE":
                overall = "PARTIAL"
            export_path = paths["csv"]

        report_path = generate_report(
            connection, paths, config, args.run_id, coverage, overall
        )
        counts = {
            row["decision"]: int(row["count"])
            for row in connection.execute(
                "SELECT decision, COUNT(*) AS count FROM evaluations WHERE run_id = ? GROUP BY decision",
                (args.run_id,),
            ).fetchall()
        }
        log_payload = {
            "run_id": args.run_id,
            "status": overall,
            "finished_at": iso_utc(),
            "coverage": coverage,
            "decision_counts": counts,
            "report_path": str(report_path),
            "csv_path": str(export_path),
            "export_error": export_error,
        }
        log_path = paths["logs"] / f"run-{args.run_id}.json"
        atomic_write_json(log_path, log_payload)
        notes = args.note
        if export_error:
            notes = (notes + f"\nCSV export error: {export_error}").strip()
        finished_at = iso_utc()
        with connection:
            connection.execute(
                """
                UPDATE runs
                SET status = ?, finished_at = ?, coverage_json = ?, notes = ?,
                    report_path = ?, export_path = ?
                WHERE run_id = ? AND status = 'RUNNING'
                """,
                (
                    overall,
                    finished_at,
                    json.dumps(coverage, ensure_ascii=False, sort_keys=True),
                    notes,
                    str(report_path),
                    str(export_path),
                    args.run_id,
                ),
            )
            require(
                connection.execute("SELECT changes()").fetchone()[0] == 1,
                f"Run {args.run_id} could not be finalized atomically",
            )
            if overall == "COMPLETE":
                set_metadata(connection, "last_completed_countries", json.dumps(config["countries"], ensure_ascii=False))
                set_metadata(connection, "last_completed_profile_hash", profile_hash)
                set_metadata(connection, "last_completed_cv_hash", cv_hash)
                set_metadata(connection, "last_completed_scoring_version", config["scoring_version"])
                set_metadata(connection, "last_completed_config_hash", config_hash)
                set_metadata(connection, "last_completed_run_id", args.run_id)
        release_run_lock(paths, args.run_id)
        return {"ok": True, **log_payload, "log_path": str(log_path)}
    finally:
        connection.close()


def command_run_abort(args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    require(paths["database"].exists(), f"Tracker database does not exist: {paths['database']}")
    connection = connect_database(paths["database"])
    try:
        require_running_run(connection, args.run_id)
        if paths["lock"].exists():
            require_run_lock(paths, args.run_id)
        finished = iso_utc()
        with connection:
            connection.execute(
                "UPDATE runs SET status = 'ABORTED', finished_at = ?, notes = ? WHERE run_id = ?",
                (finished, args.reason, args.run_id),
            )
        payload = {
            "run_id": args.run_id,
            "status": "ABORTED",
            "finished_at": finished,
            "reason": args.reason,
        }
        log_path = paths["logs"] / f"run-{args.run_id}.json"
        atomic_write_json(log_path, payload)
        release_run_lock(paths, args.run_id)
        return {"ok": True, **payload, "log_path": str(log_path)}
    finally:
        connection.close()


def command_export(_args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    config, _profile, _config_hash, _profile_hash, _cv_hash = load_runtime(paths)
    connection = connect_database(paths["database"])
    try:
        path = export_csv(connection, paths, config)
        count = int(connection.execute("SELECT COUNT(*) FROM opportunities WHERE ever_published = 1").fetchone()[0])
        return {"ok": True, "csv_path": str(path), "rows": count}
    finally:
        connection.close()


def command_stats(_args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    config, _profile, config_hash, profile_hash, cv_hash = load_runtime(paths)
    connection = connect_database(paths["database"])
    try:
        decisions = {
            row["current_decision"]: int(row["count"])
            for row in connection.execute(
                "SELECT current_decision, COUNT(*) AS count FROM opportunities GROUP BY current_decision"
            ).fetchall()
        }
        lifecycle = {
            row["lifecycle_status"]: int(row["count"])
            for row in connection.execute(
                "SELECT lifecycle_status, COUNT(*) AS count FROM opportunities GROUP BY lifecycle_status"
            ).fetchall()
        }
        return {
            "ok": True,
            "workspace": str(paths["root"]),
            "countries": config["countries"],
            "config_hash": config_hash,
            "profile_version": profile_hash[:12],
            "cv_version": cv_hash[:12],
            "opportunities_total": int(connection.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]),
            "published_history_rows": int(connection.execute("SELECT COUNT(*) FROM opportunities WHERE ever_published = 1").fetchone()[0]),
            "decisions": decisions,
            "lifecycle": lifecycle,
            "runs": int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]),
        }
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Private state manager for the PhD scholarship monitor skill")
    parser.add_argument("--workspace", required=True, help="Private monitoring workspace")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a new private workspace")
    init_parser.add_argument("--country", action="append", required=True, help="Target country; repeat as needed")
    init_parser.add_argument("--timezone", required=True, help="IANA timezone, for example Asia/Singapore")
    init_parser.add_argument("--daily-time", required=True, help="Daily local time in HH:MM")
    init_parser.set_defaults(handler=command_init)

    validate_parser = subparsers.add_parser("validate", help="Validate configuration, profile, CV, and database")
    validate_parser.add_argument("--allow-unconfirmed", action="store_true", help="Allow profile setup validation only")
    validate_parser.set_defaults(handler=command_validate)

    run_start_parser = subparsers.add_parser("run-start", help="Start a locked daily run")
    run_start_parser.set_defaults(handler=command_run_start)

    due_parser = subparsers.add_parser("due", help="List records due for re-verification")
    due_parser.add_argument("--run-id", required=True)
    due_parser.set_defaults(handler=command_due)

    lookup_parser = subparsers.add_parser("lookup", help="Look up a discovery by deterministic identity signals")
    lookup_parser.add_argument("--url")
    lookup_parser.add_argument("--official-id")
    lookup_parser.add_argument("--university")
    lookup_parser.add_argument("--title")
    lookup_parser.add_argument("--research-topic")
    lookup_parser.add_argument("--department")
    lookup_parser.add_argument("--city")
    lookup_parser.add_argument("--country")
    lookup_parser.add_argument("--supervisor")
    lookup_parser.add_argument("--deadline")
    lookup_parser.set_defaults(handler=command_lookup)

    touch_parser = subparsers.add_parser("touch", help="Record an unchanged known discovery")
    touch_parser.add_argument("--run-id", required=True)
    touch_parser.add_argument("--record-id", required=True)
    touch_parser.add_argument("--url")
    touch_parser.set_defaults(handler=command_touch)

    upsert_parser = subparsers.add_parser("candidate-upsert", help="Validate and persist one evaluated candidate packet")
    upsert_parser.add_argument("--run-id", required=True)
    upsert_parser.add_argument("--file", required=True)
    upsert_parser.set_defaults(handler=command_candidate_upsert)

    subject_parser = subparsers.add_parser(
        "review-subject",
        help="Compute the binding hash a critical reviewer must review",
    )
    subject_parser.add_argument("--file", required=True)
    subject_parser.set_defaults(handler=command_review_subject)

    finish_parser = subparsers.add_parser("run-finish", help="Finalize coverage and generate outputs")
    finish_parser.add_argument("--run-id", required=True)
    finish_parser.add_argument("--coverage", required=True)
    finish_parser.add_argument("--note", default="")
    finish_parser.set_defaults(handler=command_run_finish)

    abort_parser = subparsers.add_parser("run-abort", help="Abort a run and release its lock")
    abort_parser.add_argument("--run-id", required=True)
    abort_parser.add_argument("--reason", required=True)
    abort_parser.set_defaults(handler=command_run_abort)

    export_parser = subparsers.add_parser("export", help="Rebuild the cumulative CSV from SQLite")
    export_parser.set_defaults(handler=command_export)

    stats_parser = subparsers.add_parser("stats", help="Show aggregate tracker state")
    stats_parser.set_defaults(handler=command_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = workspace_paths(Path(args.workspace))
    try:
        result = args.handler(args, paths)
        emit(result)
        return 0
    except (ContractError, sqlite3.Error, OSError) as exc:
        print(json_dump({"ok": False, "error": str(exc), "command": args.command}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

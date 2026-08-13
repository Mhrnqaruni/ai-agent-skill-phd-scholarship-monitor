from __future__ import annotations

import csv
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "monitor-phd-scholarships" / "scripts" / "phd_tracker.py"


class TrackerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "private-monitor"
        self.cli(
            "init",
            "--country",
            "Netherlands",
            "--timezone",
            "UTC",
            "--daily-time",
            "12:00",
        )
        (self.workspace / "input" / "cv.txt").write_text(
            "MSc Computer Science. Thesis on multilingual NLP.", encoding="utf-8"
        )
        profile_path = self.workspace / "profile.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile.update(
            {
                "confirmed_by_user": True,
                "confirmed_at": self.now(),
                "education": [
                    {
                        "degree": "MSc Computer Science",
                        "status": "COMPLETED",
                        "provenance": "CV",
                    }
                ],
                "research_interests": ["multilingual natural language processing"],
                "methods": ["transformer evaluation"],
                "tools": ["Python"],
            }
        )
        profile["eligibility"]["nationalities"] = [
            {"value": "Example nationality", "provenance": "USER_CONFIRMED"}
        ]
        self.write_json(profile_path, profile)
        config_path = self.workspace / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["source_registry"]["Netherlands"]["required_core_sources"] = [
            {
                "name": "Netherlands official vacancies",
                "url": "https://official.example/netherlands",
            }
        ]
        self.write_json(config_path, config)
        self.cli("validate")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def future(days: int = 60) -> str:
        return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()

    @staticmethod
    def write_json(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def cli(self, *arguments: str, expect: int = 0) -> dict:
        command = [sys.executable, str(SCRIPT), "--workspace", str(self.workspace), *arguments]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode != expect:
            self.fail(
                f"Unexpected exit {result.returncode} for {command}\nstdout={result.stdout}\nstderr={result.stderr}"
            )
        stream = result.stdout if result.returncode == 0 else result.stderr
        return json.loads(stream)

    def start(self) -> str:
        return self.cli("run-start")["run_id"]

    def coverage(self, countries: tuple[str, ...] = ("Netherlands",), status: str = "COMPLETE") -> Path:
        payload = {"countries": {}}
        for country in countries:
            source_status = "OK" if status == "COMPLETE" else "FAILED"
            payload["countries"][country] = {
                "status": status,
                "notes": "Test coverage",
                "sources": [
                    {
                        "name": f"{country} official vacancies",
                        "url": f"https://official.example/{country.casefold()}",
                        "class": "OFFICIAL",
                        "status": source_status,
                        "checked_at": self.now(),
                        "candidates_seen": 1,
                        "note": "" if source_status == "OK" else "Simulated outage",
                    }
                ],
            }
        path = self.workspace / "coverage.json"
        self.write_json(path, payload)
        return path

    def candidate(
        self,
        *,
        suffix: str = "1",
        title: str | None = None,
        score_total: int = 87,
        funding_status: str = "VERIFIED",
        deadline_days: int = 60,
    ) -> dict:
        points = {
            87: [30, 22, 18, 13, 4],
            79: [27, 20, 16, 12, 4],
            80: [28, 20, 16, 12, 4],
            100: [35, 25, 20, 15, 5],
        }[score_total]
        deadline = self.future(deadline_days)
        official = f"https://official.example/jobs/req-{suffix}"
        application = f"https://apply.official.example/req-{suffix}"
        evidence = [
            {
                "fact": "OFFICIAL_POSTING",
                "url": official,
                "authority": "PRIMARY",
                "checked_at": self.now(),
                "summary": "Official page confirms a doctoral vacancy.",
            },
            {
                "fact": "DEADLINE",
                "url": official,
                "authority": "PRIMARY",
                "checked_at": self.now(),
                "summary": "Official page states the future deadline.",
            },
            {
                "fact": "FUNDING",
                "url": official,
                "authority": "PRIMARY",
                "checked_at": self.now(),
                "summary": "Official page states salary and full coverage.",
            },
            {
                "fact": "ELIGIBILITY",
                "url": official,
                "authority": "PRIMARY",
                "checked_at": self.now(),
                "summary": "Mandatory eligibility rules were compared.",
            },
            {
                "fact": "APPLICATION",
                "url": application,
                "authority": "AUTHORIZED_ATS",
                "checked_at": self.now(),
                "summary": "Institution-authorized application route is open.",
            },
        ]
        score = {}
        for (name, maximum), component_points in zip(
            {
                "topic_alignment": 35,
                "methods_and_skills": 25,
                "research_experience": 20,
                "academic_preparation": 15,
                "user_preferences": 5,
            }.items(),
            points,
        ):
            score[name] = {
                "points": component_points,
                "max": maximum,
                "evidence": f"Evidence for {name}",
            }
        return {
            "record_id": None,
            "official_id": f"REQ-{suffix}",
            "title": title or f"Doctoral Researcher in Multilingual NLP {suffix}",
            "research_topic": "Multilingual NLP",
            "university": "Example University",
            "department": "Computer Science",
            "city": "Amsterdam",
            "country": "Netherlands",
            "supervisor": "Professor Example",
            "doctoral_status": "CONFIRMED",
            "application_status": "VERIFIED",
            "program_deadline": deadline,
            "funding_deadline": None,
            "effective_action_deadline": deadline,
            "deadline_timezone": "UTC",
            "deadline_precision": "DATETIME",
            "deadline_status": "OPEN",
            "funding_route": "SALARY",
            "funding_status": funding_status,
            "funding_summary": "Full salary for the doctoral contract.",
            "tuition_coverage": "FULL",
            "stipend_coverage": "FULL",
            "international_fee_coverage": "FULL",
            "stipend_amount": 3500,
            "stipend_currency": "EUR",
            "stipend_period": "MONTH",
            "eligibility_status": "ELIGIBLE",
            "eligibility_summary": "All mandatory rules pass against confirmed facts.",
            "verification_confidence": 95,
            "score": score,
            "short_match_explanation": "Strong topic and methods overlap with demonstrated CV evidence.",
            "main_risk": "No material limitation identified.",
            "official_posting_url": official,
            "application_url": application,
            "funding_url": official,
            "discovery_urls": [f"https://discovery.example/items/{suffix}?utm_source=test"],
            "content_hash": None,
            "evidence": evidence,
            "review": {
                "mode": "INDEPENDENT_AGENT",
                "verdict": "PASS",
                "reviewer_id": "test-independent-reviewer",
                "subject_hash": None,
                "reviewed_at": self.now(),
                "notes": "Independent verification passed.",
            },
            "rejection_reason": None,
        }

    def prepare_packet(self, packet: dict, name: str = "subject-candidate.json") -> dict:
        if packet.get("record_id") and not packet.get("expected_prior_content_hash"):
            connection = sqlite3.connect(self.workspace / "tracker.sqlite3")
            row = connection.execute(
                "SELECT content_hash FROM opportunities WHERE record_id = ?",
                (packet["record_id"],),
            ).fetchone()
            connection.close()
            self.assertIsNotNone(row)
            packet["expected_prior_content_hash"] = row[0]
        review = packet.get("review")
        packet["review"] = None
        path = self.workspace / name
        self.write_json(path, packet)
        subject_hash = self.cli("review-subject", "--file", str(path))["subject_hash"]
        packet["review"] = review
        if isinstance(review, dict):
            review["reviewer_id"] = review.get("reviewer_id") or "test-independent-reviewer"
            review["subject_hash"] = subject_hash
        return packet

    def upsert(self, run_id: str, packet: dict, name: str = "candidate.json") -> dict:
        self.prepare_packet(packet, f"subject-{name}")
        path = self.workspace / name
        self.write_json(path, packet)
        return self.cli("candidate-upsert", "--run-id", run_id, "--file", str(path))

    def finish(self, run_id: str, *, status: str = "COMPLETE", countries: tuple[str, ...] = ("Netherlands",)) -> dict:
        return self.cli(
            "run-finish",
            "--run-id",
            run_id,
            "--coverage",
            str(self.coverage(countries, status)),
        )

    def test_publish_persists_and_second_run_deduplicates(self) -> None:
        first_run = self.start()
        result = self.upsert(first_run, self.candidate())
        self.assertEqual("PUBLISH", result["decision"])
        record_id = result["record_id"]
        self.finish(first_run)

        with (self.workspace / "opportunities.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(1, len(rows))
        self.assertEqual(record_id, rows[0]["record_id"])
        self.assertEqual("87.0", rows[0]["current_match_score"])

        second_run = self.start()
        lookup = self.cli("lookup", "--url", "https://discovery.example/items/1?utm_medium=email")
        self.assertTrue(lookup["found"])
        self.assertFalse(lookup["recheck_due"])
        self.cli(
            "touch",
            "--run-id",
            second_run,
            "--record-id",
            record_id,
            "--url",
            "https://discovery.example/items/1?utm_medium=email",
        )
        self.finish(second_run)
        stats = self.cli("stats")
        self.assertEqual(1, stats["opportunities_total"])
        self.assertEqual(1, stats["published_history_rows"])

    def test_score_below_80_is_stored_but_not_exported(self) -> None:
        run_id = self.start()
        result = self.upsert(run_id, self.candidate(score_total=79))
        self.assertEqual("UNDER_THRESHOLD", result["decision"])
        self.assertFalse(result["visible_in_csv"])
        self.finish(run_id)
        stats = self.cli("stats")
        self.assertEqual(1, stats["opportunities_total"])
        self.assertEqual(0, stats["published_history_rows"])
        with (self.workspace / "opportunities.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            self.assertEqual([], list(csv.DictReader(handle)))

    def test_score_exactly_80_is_publishable(self) -> None:
        run_id = self.start()
        result = self.upsert(run_id, self.candidate(score_total=80))
        self.assertEqual("PUBLISH", result["decision"])
        self.finish(run_id)

    def test_unknown_funding_holds_high_score(self) -> None:
        run_id = self.start()
        packet = self.candidate(score_total=100, funding_status="NOT_VERIFIED")
        result = self.upsert(run_id, packet)
        self.assertEqual("HOLD", result["decision"])
        self.assertIn("funding is not verified", result["reasons"])
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_automatic_consideration_is_rejected_by_safe_default(self) -> None:
        run_id = self.start()
        packet = self.candidate(score_total=100)
        packet["funding_route"] = "AUTOMATIC_CONSIDERATION"
        result = self.upsert(run_id, packet)
        self.assertEqual("REJECT", result["decision"])
        self.assertTrue(any("not accepted" in reason for reason in result["reasons"]))
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_configured_stipend_floor_is_enforced(self) -> None:
        config_path = self.workspace / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["funding_policy"].update(
            {
                "minimum_stipend": 4000,
                "minimum_stipend_currency": "EUR",
                "minimum_stipend_period": "MONTH",
            }
        )
        self.write_json(config_path, config)
        run_id = self.start()
        result = self.upsert(run_id, self.candidate(score_total=100))
        self.assertEqual("REJECT", result["decision"])
        self.assertTrue(any("below" in reason for reason in result["reasons"]))
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_past_deadline_rejects(self) -> None:
        run_id = self.start()
        result = self.upsert(run_id, self.candidate(deadline_days=-1))
        self.assertEqual("REJECT", result["decision"])
        self.assertEqual("EXPIRED", result["lifecycle_status"])
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_secondary_only_expiry_cannot_suppress_candidate(self) -> None:
        run_id = self.start()
        packet = self.candidate(deadline_days=-1)
        for evidence in packet["evidence"]:
            if evidence["fact"] == "DEADLINE":
                evidence["authority"] = "SECONDARY"
        result = self.upsert(run_id, packet)
        self.assertEqual("HOLD", result["decision"])
        self.assertTrue(any("authoritative deadline" in reason for reason in result["reasons"]))
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_missing_application_evidence_holds(self) -> None:
        run_id = self.start()
        packet = self.candidate()
        packet["evidence"] = [item for item in packet["evidence"] if item["fact"] != "APPLICATION"]
        result = self.upsert(run_id, packet)
        self.assertEqual("HOLD", result["decision"])
        self.assertTrue(any("application evidence" in reason for reason in result["reasons"]))
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_profile_change_marks_active_record_due(self) -> None:
        first_run = self.start()
        self.upsert(first_run, self.candidate())
        self.finish(first_run)
        profile_path = self.workspace / "profile.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["research_interests"].append("low-resource evaluation")
        profile["confirmed_at"] = self.now()
        self.write_json(profile_path, profile)
        second_run = self.start()
        due = self.cli("due", "--run-id", second_run)
        self.assertTrue(due["records"])
        self.assertEqual("profile_changed", due["records"][0]["reason"])
        self.cli("run-abort", "--run-id", second_run, "--reason", "test complete")

    def test_country_change_is_detected_and_history_retained(self) -> None:
        first_run = self.start()
        self.upsert(first_run, self.candidate())
        self.finish(first_run)
        config_path = self.workspace / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["countries"] = ["Germany"]
        config["source_registry"]["Germany"] = {"required_core_sources": [], "local_terms": []}
        self.write_json(config_path, config)
        second = self.cli("run-start")
        self.assertEqual(["Germany"], second["countries_added"])
        self.assertEqual(["Netherlands"], second["countries_removed"])
        self.cli("run-abort", "--run-id", second["run_id"], "--reason", "test complete")
        stats = self.cli("stats")
        self.assertEqual(1, stats["published_history_rows"])
        self.assertEqual(1, stats["lifecycle"]["OUT_OF_SCOPE"])

    def test_partial_source_failure_does_not_close_record(self) -> None:
        first_run = self.start()
        self.upsert(first_run, self.candidate())
        self.finish(first_run)
        second_run = self.start()
        outcome = self.finish(second_run, status="FAILED")
        self.assertEqual("FAILED", outcome["status"])
        connection = sqlite3.connect(self.workspace / "tracker.sqlite3")
        lifecycle = connection.execute("SELECT lifecycle_status FROM opportunities").fetchone()[0]
        connection.close()
        self.assertIn(lifecycle, {"ACTIVE", "CLOSING_SOON"})

    def test_formula_injection_is_neutralized_in_csv(self) -> None:
        run_id = self.start()
        packet = self.candidate(title="=HYPERLINK(\"https://evil.example\",\"click\")")
        result = self.upsert(run_id, packet)
        self.assertEqual("PUBLISH", result["decision"])
        self.finish(run_id)
        with (self.workspace / "opportunities.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertTrue(row["title"].startswith("'="))

    def test_tab_prefixed_spreadsheet_payload_is_neutralized(self) -> None:
        run_id = self.start()
        packet = self.candidate(title="\t=HYPERLINK(\"https://evil.example\")")
        result = self.upsert(run_id, packet)
        self.assertEqual("PUBLISH", result["decision"])
        self.finish(run_id)
        with (self.workspace / "opportunities.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            row = next(csv.DictReader(handle))
        self.assertTrue(row["title"].startswith("'"))

    def test_overlapping_run_is_refused(self) -> None:
        run_id = self.start()
        error = self.cli("run-start", expect=2)
        self.assertIn("refusing overlapping writes", error["error"])
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_mid_run_profile_drift_blocks_writes(self) -> None:
        run_id = self.start()
        profile_path = self.workspace / "profile.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["research_interests"].append("new interest during run")
        profile["confirmed_at"] = self.now()
        self.write_json(profile_path, profile)
        path = self.workspace / "candidate.json"
        packet = self.prepare_packet(self.candidate())
        self.write_json(path, packet)
        error = self.cli(
            "candidate-upsert", "--run-id", run_id, "--file", str(path), expect=2
        )
        self.assertIn("snapshot drift", error["error"])
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_mid_run_cv_drift_blocks_writes(self) -> None:
        run_id = self.start()
        packet = self.prepare_packet(self.candidate())
        (self.workspace / "input" / "cv.txt").write_text(
            "A materially different CV was placed here during the run.",
            encoding="utf-8",
        )
        path = self.workspace / "candidate.json"
        self.write_json(path, packet)
        error = self.cli(
            "candidate-upsert", "--run-id", run_id, "--file", str(path), expect=2
        )
        self.assertIn("CV input changed", error["error"])
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_cv_change_between_runs_requires_profile_reconfirmation(self) -> None:
        first_run = self.start()
        self.finish(first_run)
        (self.workspace / "input" / "cv.txt").write_text(
            "The CV changed after the completed baseline.", encoding="utf-8"
        )
        error = self.cli("run-start", expect=2)
        self.assertIn("profile.json was not updated and reconfirmed", error["error"])
        self.assertFalse((self.workspace / ".run.lock").exists())

    def test_first_promotion_from_hold_is_reported_as_new(self) -> None:
        first_run = self.start()
        held = self.candidate(funding_status="NOT_VERIFIED")
        first = self.upsert(first_run, held)
        self.assertEqual("HOLD", first["decision"])
        record_id = first["record_id"]
        self.finish(first_run)

        second_run = self.start()
        publishable = self.candidate()
        publishable["record_id"] = record_id
        promoted = self.upsert(second_run, publishable)
        self.assertEqual("NEW_PUBLISHED", promoted["event"])
        outcome = self.finish(second_run)
        report = Path(outcome["report_path"]).read_text(encoding="utf-8")
        self.assertIn("New verified matches scoring at least 80: **1**", report)

    def test_caller_cannot_override_tracker_content_hash(self) -> None:
        run_id = self.start()
        packet = self.candidate()
        packet["content_hash"] = "0" * 64
        path = self.workspace / "candidate.json"
        self.write_json(path, packet)
        error = self.cli(
            "candidate-upsert", "--run-id", run_id, "--file", str(path), expect=2
        )
        self.assertIn("tracker-computed", error["error"])
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_record_id_cannot_overwrite_unrelated_candidate(self) -> None:
        run_id = self.start()
        first = self.upsert(run_id, self.candidate(suffix="identity-a"), "first.json")
        second = self.candidate(suffix="identity-b")
        second["record_id"] = first["record_id"]
        self.prepare_packet(second, "identity-subject.json")
        path = self.workspace / "identity-overwrite.json"
        self.write_json(path, second)
        error = self.cli(
            "candidate-upsert", "--run-id", run_id, "--file", str(path), expect=2
        )
        self.assertIn("cannot remove or replace the canonical official_id", error["error"])
        connection = sqlite3.connect(self.workspace / "tracker.sqlite3")
        stored = connection.execute(
            "SELECT official_id, title FROM opportunities WHERE record_id = ?",
            (first["record_id"],),
        ).fetchone()
        connection.close()
        self.assertEqual("REQ-identity-a", stored[0])
        self.assertIn("identity-a", stored[1])
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_critical_review_cannot_be_replayed_across_candidates(self) -> None:
        run_id = self.start()
        first = self.prepare_packet(self.candidate(suffix="review-a"), "review-a.json")
        second = self.prepare_packet(self.candidate(suffix="review-b"), "review-b.json")
        second["review"] = json.loads(json.dumps(first["review"]))
        path = self.workspace / "review-replay.json"
        self.write_json(path, second)
        error = self.cli(
            "candidate-upsert", "--run-id", run_id, "--file", str(path), expect=2
        )
        self.assertIn("not bound to this normalized candidate", error["error"])
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_critical_review_is_bound_to_confirmed_profile(self) -> None:
        packet = self.prepare_packet(self.candidate(suffix="profile-bound"))
        profile_path = self.workspace / "profile.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["research_interests"].append("a newly confirmed research interest")
        profile["confirmed_at"] = self.now()
        self.write_json(profile_path, profile)
        run_id = self.start()
        path = self.workspace / "stale-profile-review.json"
        self.write_json(path, packet)
        error = self.cli(
            "candidate-upsert", "--run-id", run_id, "--file", str(path), expect=2
        )
        self.assertIn("not bound to this normalized candidate", error["error"])
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_required_source_url_cannot_be_spoofed_by_name(self) -> None:
        config_path = self.workspace / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["source_registry"]["Netherlands"]["required_core_sources"] = [
            {
                "name": "Trusted Official Registry",
                "url": "https://trusted.example/jobs",
            }
        ]
        self.write_json(config_path, config)
        run_id = self.start()
        coverage = {
            "countries": {
                "Netherlands": {
                    "status": "COMPLETE",
                    "notes": "Attempted name-only substitution.",
                    "sources": [
                        {
                            "name": "Trusted Official Registry",
                            "url": "https://evil.example/not-trusted",
                            "class": "OFFICIAL",
                            "status": "OK",
                            "checked_at": self.now(),
                            "candidates_seen": 0,
                            "note": "",
                        }
                    ],
                }
            }
        }
        path = self.workspace / "spoofed-coverage.json"
        self.write_json(path, coverage)
        outcome = self.cli(
            "run-finish", "--run-id", run_id, "--coverage", str(path)
        )
        self.assertEqual("PARTIAL", outcome["status"])
        self.assertIn(
            "Missing successful required core sources",
            outcome["coverage"]["countries"]["Netherlands"]["notes"],
        )

    def test_complete_coverage_requires_configured_sources(self) -> None:
        config_path = self.workspace / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["source_registry"]["Netherlands"]["required_core_sources"] = []
        self.write_json(config_path, config)
        run_id = self.start()
        outcome = self.finish(run_id)
        self.assertEqual("PARTIAL", outcome["status"])
        self.assertIn(
            "No required core sources",
            outcome["coverage"]["countries"]["Netherlands"]["notes"],
        )

    def test_empty_complete_coverage_is_failed(self) -> None:
        run_id = self.start()
        path = self.workspace / "empty-coverage.json"
        self.write_json(
            path,
            {
                "countries": {
                    "Netherlands": {
                        "status": "COMPLETE",
                        "notes": "",
                        "sources": [],
                    }
                }
            },
        )
        outcome = self.cli(
            "run-finish", "--run-id", run_id, "--coverage", str(path)
        )
        self.assertEqual("FAILED", outcome["status"])

    def test_stale_coverage_timestamp_is_rejected_without_finalizing(self) -> None:
        run_id = self.start()
        path = self.coverage()
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["countries"]["Netherlands"]["sources"][0]["checked_at"] = (
            datetime.now(timezone.utc) - timedelta(days=3)
        ).replace(microsecond=0).isoformat()
        self.write_json(path, payload)
        error = self.cli(
            "run-finish", "--run-id", run_id, "--coverage", str(path), expect=2
        )
        self.assertIn("older than", error["error"])
        self.assertTrue((self.workspace / ".run.lock").exists())
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_effective_deadline_is_derived_from_earliest_component(self) -> None:
        run_id = self.start()
        packet = self.candidate()
        earlier = self.future(20)
        later = self.future(60)
        packet["program_deadline"] = later
        packet["funding_deadline"] = earlier
        packet["effective_action_deadline"] = later
        result = self.upsert(run_id, packet)
        self.assertEqual("HOLD", result["decision"])
        self.assertTrue(any("earliest" in reason for reason in result["reasons"]))
        connection = sqlite3.connect(self.workspace / "tracker.sqlite3")
        stored = connection.execute(
            "SELECT effective_action_deadline FROM opportunities"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(earlier, stored)
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_fingerprint_collision_requires_explicit_distinct_review(self) -> None:
        run_id = self.start()
        first = self.candidate(suffix="a", title="Generic Doctoral Researcher")
        first["official_id"] = None
        first_result = self.upsert(run_id, first, "first.json")

        second = self.candidate(suffix="b", title="Generic Doctoral Researcher")
        second["official_id"] = None
        for key in (
            "program_deadline",
            "funding_deadline",
            "effective_action_deadline",
        ):
            second[key] = first[key]
        self.prepare_packet(second)
        path = self.workspace / "second.json"
        self.write_json(path, second)
        error = self.cli(
            "candidate-upsert", "--run-id", run_id, "--file", str(path), expect=2
        )
        self.assertIn("Potential duplicate fingerprint", error["error"])

        second["duplicate_review"] = {
            "verdict": "DISTINCT",
            "record_ids": [first_result["record_id"]],
            "reviewed_at": self.now(),
            "reason": "Different authoritative vacancy and application route.",
        }
        second_result = self.upsert(run_id, second, "second-reviewed.json")
        self.assertNotEqual(first_result["record_id"], second_result["record_id"])
        connection = sqlite3.connect(self.workspace / "tracker.sqlite3")
        count = connection.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        connection.close()
        self.assertEqual(2, count)
        self.cli("run-abort", "--run-id", run_id, "--reason", "test complete")

    def test_finalize_failure_leaves_run_recoverable(self) -> None:
        run_id = self.start()
        reports = self.workspace / "reports"
        reports.rmdir()
        reports.write_text("blocks report directory", encoding="utf-8")
        coverage = self.coverage()
        error = self.cli(
            "run-finish", "--run-id", run_id, "--coverage", str(coverage), expect=2
        )
        self.assertTrue(error["error"])
        connection = sqlite3.connect(self.workspace / "tracker.sqlite3")
        status = connection.execute(
            "SELECT status FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        connection.close()
        self.assertEqual("RUNNING", status)
        self.assertTrue((self.workspace / ".run.lock").exists())
        reports.unlink()
        reports.mkdir()
        outcome = self.cli(
            "run-finish", "--run-id", run_id, "--coverage", str(coverage)
        )
        self.assertEqual("COMPLETE", outcome["status"])

    def test_schema_one_workspace_migrates_to_current_schema(self) -> None:
        connection = sqlite3.connect(self.workspace / "tracker.sqlite3")
        connection.execute("ALTER TABLE opportunities DROP COLUMN stipend_amount")
        connection.execute("ALTER TABLE opportunities DROP COLUMN stipend_currency")
        connection.execute("ALTER TABLE opportunities DROP COLUMN stipend_period")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
        connection.close()
        self.cli("validate")
        connection = sqlite3.connect(self.workspace / "tracker.sqlite3")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(opportunities)").fetchall()
        }
        connection.close()
        self.assertEqual(3, version)
        self.assertTrue(
            {"stipend_amount", "stipend_currency", "stipend_period"}.issubset(columns)
        )

    def test_schema_two_workspace_adds_cv_snapshot_columns(self) -> None:
        connection = sqlite3.connect(self.workspace / "tracker.sqlite3")
        connection.execute("ALTER TABLE runs DROP COLUMN cv_hash")
        connection.execute("ALTER TABLE runs DROP COLUMN cv_changed")
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
        connection.close()
        self.cli("validate")
        connection = sqlite3.connect(self.workspace / "tracker.sqlite3")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
        }
        connection.close()
        self.assertEqual(3, version)
        self.assertTrue({"cv_hash", "cv_changed"}.issubset(columns))

    def test_finished_run_lock_is_recovered_on_next_start(self) -> None:
        first_run = self.start()
        self.finish(first_run)
        self.write_json(
            self.workspace / ".run.lock",
            {
                "run_id": first_run,
                "created_at": self.now(),
                "pid": 1,
                "tracker_version": "test",
            },
        )
        second = self.cli("run-start")
        self.assertTrue(second["recovered_finished_lock"])
        self.cli("run-abort", "--run-id", second["run_id"], "--reason", "test complete")

    def test_report_escapes_untrusted_html(self) -> None:
        run_id = self.start()
        packet = self.candidate(title="<script>alert(1)</script>")
        self.upsert(run_id, packet)
        outcome = self.finish(run_id)
        report = Path(outcome["report_path"]).read_text(encoding="utf-8")
        self.assertNotIn("<script>", report)
        self.assertIn("&lt;script&gt;", report)


if __name__ == "__main__":
    unittest.main()

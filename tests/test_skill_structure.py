from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "monitor-phd-scholarships"


class SkillStructureTestCase(unittest.TestCase):
    def test_skill_frontmatter_and_metadata(self) -> None:
        content = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\n"))
        _, frontmatter, body = content.split("---", 2)
        keys = [
            line.split(":", 1)[0].strip()
            for line in frontmatter.splitlines()
            if line.strip()
        ]
        self.assertEqual(["name", "description"], keys)
        self.assertIn("name: monitor-phd-scholarships", frontmatter)
        self.assertIn("funded PhD", frontmatter)
        self.assertNotRegex(body, r"(?i)\bTODO\b|\bFIXME\b")

        metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "PhD Scholarship Monitor"', metadata)
        self.assertIn("$monitor-phd-scholarships", metadata)

    def test_every_linked_reference_exists_and_every_reference_is_linked(self) -> None:
        content = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        linked = set(re.findall(r"\(references/([^)]+\.md)\)", content))
        actual = {path.name for path in (SKILL_ROOT / "references").glob("*.md")}
        self.assertEqual(actual, linked)

    def test_public_repository_contains_no_private_monitor_artifacts(self) -> None:
        forbidden_suffixes = {
            ".pdf",
            ".doc",
            ".docx",
            ".rtf",
            ".sqlite3",
            ".sqlite3-wal",
            ".sqlite3-shm",
        }
        forbidden_names = {"profile.json", "config.json", "opportunities.csv", ".run.lock"}
        violations = []
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if path.name in forbidden_names or path.suffix.casefold() in forbidden_suffixes:
                violations.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual([], violations)

    def test_tracker_has_no_third_party_imports(self) -> None:
        script = (SKILL_ROOT / "scripts" / "phd_tracker.py").read_text(encoding="utf-8")
        forbidden = ["requests", "yaml", "pandas", "openpyxl", "bs4"]
        for module in forbidden:
            self.assertNotRegex(script, rf"(?m)^\s*(?:from|import)\s+{module}\b")


if __name__ == "__main__":
    unittest.main()

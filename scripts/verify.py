#!/usr/bin/env python3
"""Verify the publishable CTO repository without downloading third-party skills."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPOSITORY_ROOT / "skills" / "cto"
EXPECTED_SKILLS = 193
REQUIRED_FILES = (
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "THIRD_PARTY_SOURCES.md",
    "skills/cto/SKILL.md",
    "skills/cto/references/capability-map.md",
    "skills/cto/references/recovery.json",
    "skills/cto/references/subskills.json",
    "skills/cto/scripts/generate_notices.py",
    "skills/cto/scripts/select_subskills.py",
    "skills/cto/scripts/sync_subskills.py",
    "skills/cto/scripts/validate_bundle.py",
)
IGNORED_PUBLIC_PATHS = (
    ".agents/example",
    "skills-lock.json",
    "skills/cto/subskills/example/SKILL.md",
    "skills/cto/references/sync-report.json",
    "skills/cto/references/audit-report.json",
    "skills/cto/THIRD_PARTY_NOTICES.md",
)


def run(command: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def validate_required_files() -> None:
    missing = [path for path in REQUIRED_FILES if not (REPOSITORY_ROOT / path).is_file()]
    if missing:
        raise ValueError("Missing required repository files: " + ", ".join(missing))


def validate_frontmatter() -> None:
    content = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    if not content.startswith("---\n") or "\n---\n" not in content[4:]:
        raise ValueError("skills/cto/SKILL.md has invalid frontmatter delimiters")
    frontmatter = content.split("\n---\n", 1)[0][4:]
    expected = {
        "name": "cto",
        "version": "1.0.0",
        "license": "MIT",
    }
    for field, value in expected.items():
        if not re.search(rf"(?m)^{field}:\s*{re.escape(value)}\s*$", frontmatter):
            raise ValueError(f"Missing frontmatter value: {field}: {value}")
    if "https://github.com/MAnasLatif/CTO" not in frontmatter:
        raise ValueError("Canonical repository URL is missing from skill frontmatter")


def validate_python_syntax() -> None:
    scripts = sorted((REPOSITORY_ROOT / "scripts").glob("*.py"))
    scripts.extend(sorted((SKILL_ROOT / "scripts").glob("*.py")))
    for script in scripts:
        ast.parse(script.read_text(encoding="utf-8"), filename=str(script))


def validate_manifest() -> None:
    canonical_manifest = SKILL_ROOT / "references" / "subskills.json"
    manifest = json.loads(canonical_manifest.read_text(encoding="utf-8"))
    entries = manifest.get("skills", [])
    summary = manifest.get("summary", {})

    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported sub-skill manifest schema")
    if len(entries) != EXPECTED_SKILLS:
        raise ValueError(f"Expected {EXPECTED_SKILLS} catalog entries")
    if summary.get("unique_source_skill_pairs") != EXPECTED_SKILLS:
        raise ValueError("Manifest summary has an unexpected specialist count")

    ids = [entry.get("id") for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("Manifest contains duplicate source-qualified IDs")
    if ids != sorted(ids, key=str.lower):
        raise ValueError("Manifest entries are not deterministically ordered")

    for entry in entries:
        expected_id = (
            f"{entry.get('owner')}/{entry.get('repository')}#{entry.get('skill')}"
        )
        expected_source = (
            f"https://github.com/{entry.get('owner')}/{entry.get('repository')}"
        )
        if entry.get("id") != expected_id or entry.get("source") != expected_source:
            raise ValueError(f"Invalid catalog identity: {entry.get('id')}")


def validate_manifest_and_wrapper() -> None:
    validate_manifest()
    with tempfile.TemporaryDirectory(prefix="cto-verify-") as temporary:
        temporary_path = Path(temporary)
        audit_path = temporary_path / "audit.json"
        run(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "validate_bundle.py"),
                "--allow-missing",
                "--output",
                str(audit_path),
            ],
            capture_output=True,
        )
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        summary = audit["summary"]
        if summary["expected_skills"] != EXPECTED_SKILLS:
            raise ValueError("Unexpected specialist count")
        if summary["installed_skills"] + summary["missing_skills"] != EXPECTED_SKILLS:
            raise ValueError("Installed and missing specialist counts do not reconcile")
        for key in ("invalid_names", "digest_mismatches", "symlinks"):
            if summary[key] != 0:
                raise ValueError(f"Bundle validation failed: {key}={summary[key]}")

        selection = run(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "select_subskills.py"),
                "architecture security reliability strategy",
                "--include-missing",
                "--json",
            ],
            capture_output=True,
        )
        selected = json.loads(selection.stdout)
        if not 1 <= len(selected) <= 5:
            raise ValueError("Selector did not return one to five specialists")
        if not all(item.get("id") and item.get("skill_file") for item in selected):
            raise ValueError("Selector returned an incomplete record")


def validate_git_boundary() -> None:
    for path in IGNORED_PUBLIC_PATHS:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", path],
            cwd=REPOSITORY_ROOT,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError(f"Generated or third-party path is not ignored: {path}")

    tracked = run(["git", "ls-files", "-z"], capture_output=True).stdout.split("\0")
    forbidden = [
        path
        for path in tracked
        if path.startswith(".agents/") or path.startswith("skills/cto/subskills/")
    ]
    if forbidden:
        raise ValueError("Third-party or local files are tracked: " + ", ".join(forbidden))


def main() -> None:
    validate_required_files()
    validate_frontmatter()
    validate_python_syntax()
    validate_manifest_and_wrapper()
    validate_git_boundary()
    print("Repository verification passed: 193 catalog entries, public wrapper only.")


if __name__ == "__main__":
    main()
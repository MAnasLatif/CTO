#!/usr/bin/env python3
"""Validate completeness, provenance, and basic safety of the CTO bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = SKILL_ROOT / "references" / "subskills.json"
DEFAULT_SYNC_REPORT = SKILL_ROOT / "references" / "sync-report.json"
DEFAULT_AUDIT_REPORT = SKILL_ROOT / "references" / "audit-report.json"
RISK_PATTERNS = {
    "pipe_to_shell": re.compile(r"(?:curl|wget)[^\n|]{0,300}\|\s*(?:sh|bash)\b", re.I),
    "recursive_delete": re.compile(r"\brm\s+-[^\n]*r[^\n]*f|\brm\s+-[^\n]*f[^\n]*r", re.I),
    "sudo": re.compile(r"\bsudo\b"),
    "dynamic_eval": re.compile(r"\beval\s*[(` ]"),
}
TEXT_SUFFIXES = {"", ".md", ".txt", ".py", ".js", ".ts", ".sh", ".json", ".yaml", ".yml"}
SCRIPT_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".zsh", ".ps1"}
LICENSE_PREFIXES = ("license", "licence", "copying")
INSTALLER_EXCLUDED_FILES = frozenset({"metadata.json"})
MANUAL_REVIEWS = [
    {
        "id": "axiom-sre-trusted-config-execution",
        "severity": "high_if_untrusted",
        "status": "guarded",
        "paths": [
            "subskills/axiomhq--skills/axiom-sre/scripts/config",
            "subskills/axiomhq--skills/axiom-sre/scripts/curl-auth",
        ],
        "finding": (
            "The config helper emits shell assignments from config.toml values that "
            "callers evaluate, and curl-auth may execute access_command from that config."
        ),
        "required_control": (
            "Treat SRE_CONFIG and config.toml as executable trusted input. Never invoke "
            "these scripts automatically; require explicit user approval after reviewing "
            "the config, command, destination endpoint, and requested scope."
        ),
    }
]


def source_key(entry: dict) -> str:
    return f"{entry['owner']}--{entry['repository']}"


def tree_digest(
    directory: Path, excluded_files: set[str] | frozenset[str] = frozenset()
) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        relative_path = path.relative_to(directory).as_posix()
        if relative_path in excluded_files:
            continue
        relative = relative_path.encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def frontmatter_name(skill_file: Path) -> str | None:
    content = skill_file.read_text(encoding="utf-8", errors="replace")
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end == -1:
        return None
    match = re.search(r"(?m)^name:\s*['\"]?([^'\"\s]+)", content[3:end])
    return match.group(1) if match else None


def frontmatter_license(skill_file: Path) -> str | None:
    content = skill_file.read_text(encoding="utf-8", errors="replace")
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end == -1:
        return None
    match = re.search(r"(?m)^license:\s*['\"]?([^'\"\n]+)", content[3:end])
    return match.group(1).strip() if match else None


def is_license_file(path: Path) -> bool:
    return path.name.lower().startswith(LICENSE_PREFIXES)


def scan_files(
    directory: Path,
) -> tuple[Counter, dict[str, list[str]], list[str], list[str], list[str], list[str]]:
    risks: Counter = Counter()
    risk_findings: dict[str, list[str]] = defaultdict(list)
    scripts: list[str] = []
    executables: list[str] = []
    symlinks: list[str] = []
    license_files: list[str] = []
    for path in directory.rglob("*"):
        relative = str(path.relative_to(SKILL_ROOT))
        if path.is_symlink():
            symlinks.append(relative)
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in SCRIPT_SUFFIXES:
            scripts.append(relative)
        if os.access(path, os.X_OK):
            executables.append(relative)
        if is_license_file(path):
            license_files.append(relative)
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 1_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in RISK_PATTERNS.items():
            if pattern.search(text):
                risks[label] += 1
                risk_findings[label].append(relative)
    return risks, risk_findings, scripts, executables, symlinks, license_files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--sync-report", type=Path, default=DEFAULT_SYNC_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_AUDIT_REPORT)
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    sync_report = (
        json.loads(args.sync_report.read_text(encoding="utf-8"))
        if args.sync_report.exists()
        else {"skills": []}
    )
    synced = {record["id"]: record for record in sync_report.get("skills", [])}

    missing: list[str] = []
    invalid_names: list[dict] = []
    digest_mismatches: list[dict] = []
    installer_normalizations: list[dict] = []
    symlinks: list[str] = []
    risk_counts: Counter = Counter()
    risk_findings: dict[str, set[str]] = defaultdict(set)
    script_paths: set[str] = set()
    executable_paths: set[str] = set()
    installed = 0
    sources_with_legal_files: set[str] = set()
    source_license_evidence: dict[str, dict] = {}

    for entry in manifest["skills"]:
        directory = SKILL_ROOT / "subskills" / source_key(entry) / entry["skill"]
        skill_file = directory / "SKILL.md"
        if not skill_file.exists():
            missing.append(entry["id"])
            continue
        installed += 1
        actual_name = frontmatter_name(skill_file)
        if actual_name != entry["skill"]:
            invalid_names.append(
                {"id": entry["id"], "expected": entry["skill"], "actual": actual_name}
            )

        record = synced.get(entry["id"])
        if record and record.get("sha256"):
            actual_digest = tree_digest(directory)
            if actual_digest != record["sha256"]:
                excluded_files = set(record.get("install_excluded_files", []))
                normalized_digest = tree_digest(directory, excluded_files)
                valid_normalization = (
                    bool(excluded_files)
                    and excluded_files.issubset(INSTALLER_EXCLUDED_FILES)
                    and all(not (directory / path).exists() for path in excluded_files)
                    and normalized_digest == record.get("install_sha256")
                )
                if valid_normalization:
                    installer_normalizations.append(
                        {"id": entry["id"], "omitted_files": sorted(excluded_files)}
                    )
                else:
                    digest_mismatches.append(
                        {
                            "id": entry["id"],
                            "expected": record["sha256"],
                            "actual": actual_digest,
                        }
                    )

        risks, found_risks, scripts, executables, found_symlinks, local_license_files = scan_files(directory)
        risk_counts.update(risks)
        for label, paths in found_risks.items():
            risk_findings[label].update(paths)
        script_paths.update(scripts)
        executable_paths.update(executables)
        symlinks.extend(found_symlinks)
        declared_license = frontmatter_license(skill_file)
        evidence = source_license_evidence.setdefault(
            entry["source"],
            {
                "source": entry["source"],
                "source_license_files": set(),
                "bundled_license_files": set(),
                "declared_licenses": set(),
                "unknown_skills": [],
                "skill_statuses": [],
            },
        )
        if record:
            legal_files = [SKILL_ROOT / path for path in record.get("source_legal_files", [])]
            if legal_files and all(path.exists() for path in legal_files):
                sources_with_legal_files.add(entry["source"])
            source_license_files = [
                str(path.relative_to(SKILL_ROOT))
                for path in legal_files
                if path.exists() and is_license_file(path)
            ]
        else:
            source_license_files = []
        evidence["source_license_files"].update(source_license_files)
        evidence["bundled_license_files"].update(local_license_files)
        if declared_license:
            evidence["declared_licenses"].add(declared_license)
        if source_license_files or local_license_files:
            evidence["skill_statuses"].append("license_text")
        elif declared_license:
            evidence["skill_statuses"].append("declaration_only")
        else:
            evidence["skill_statuses"].append("unknown")
            evidence["unknown_skills"].append(entry["id"])

    license_evidence_records: list[dict] = []
    license_review: list[dict] = []
    license_status_counts: Counter = Counter()
    for source, evidence in sorted(source_license_evidence.items()):
        statuses = evidence.pop("skill_statuses")
        if "unknown" in statuses:
            status = "unknown"
        elif "declaration_only" in statuses:
            status = "declaration_only"
        else:
            status = "license_text"
        license_status_counts[status] += 1
        normalized = {
            "source": source,
            "status": status,
            "source_license_files": sorted(evidence["source_license_files"]),
            "bundled_license_files": sorted(evidence["bundled_license_files"]),
            "declared_licenses": sorted(evidence["declared_licenses"]),
            "unknown_skills": sorted(evidence["unknown_skills"]),
        }
        license_evidence_records.append(normalized)
        if status != "license_text":
            license_review.append(normalized)

    expected = manifest["summary"]["unique_source_skill_pairs"]
    audit = {
        "schema_version": 1,
        "summary": {
            "expected_skills": expected,
            "installed_skills": installed,
            "missing_skills": len(missing),
            "invalid_names": len(invalid_names),
            "digest_mismatches": len(digest_mismatches),
            "installer_normalizations": len(installer_normalizations),
            "symlinks": len(symlinks),
            "script_files": len(script_paths),
            "executable_files": len(executable_paths),
            "sources_with_legal_files": len(sources_with_legal_files),
            "sources_with_license_text": license_status_counts["license_text"],
            "sources_with_declarations_only": license_status_counts["declaration_only"],
            "sources_with_unknown_license": license_status_counts["unknown"],
            "total_sources": len({entry["source"] for entry in manifest["skills"]}),
            "manual_review_findings": len(MANUAL_REVIEWS),
        },
        "missing": missing,
        "invalid_names": invalid_names,
        "digest_mismatches": digest_mismatches,
        "installer_normalizations": installer_normalizations,
        "symlinks": symlinks,
        "static_risk_indicators": dict(sorted(risk_counts.items())),
        "static_risk_findings": {
            label: sorted(paths) for label, paths in sorted(risk_findings.items())
        },
        "script_paths": sorted(script_paths),
        "executable_paths": sorted(executable_paths),
        "license_evidence": license_evidence_records,
        "license_review": license_review,
        "manual_reviews": MANUAL_REVIEWS,
        "notes": [
            "Static command indicators are file-level matches that require human review and are not proof of malicious behavior.",
            "License declarations without applicable license text and unknown licenses require review before public redistribution.",
            "Recovery-archive licenses do not replace the original source's license.",
            "Installer normalizations permit only allowlisted files that the Skills CLI omits from copied payloads.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit["summary"], indent=2))

    hard_failures = invalid_names or digest_mismatches or symlinks
    if missing and not args.allow_missing:
        hard_failures = True
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate source and license notices for bundled CTO sub-skills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
LICENSE_PREFIXES = ("license", "licence", "copying")


def source_key(entry: dict) -> str:
    return f"{entry['owner']}--{entry['repository']}"


def source_label(entry: dict) -> str:
    return f"{entry['owner']}/{entry['repository']}"


def legal_cell(paths: list[str]) -> str:
    return "<br>".join(f"[`{Path(item).name}`]({item})" for item in paths)


def is_license_path(path: str) -> bool:
    return Path(path).name.lower().startswith(LICENSE_PREFIXES)


def bundled_license_files(entry: dict) -> list[str]:
    directory = SKILL_ROOT / "subskills" / source_key(entry) / entry["skill"]
    return sorted(
        str(path.relative_to(SKILL_ROOT))
        for path in directory.rglob("*")
        if path.is_file() and is_license_path(str(path))
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=SKILL_ROOT / "references" / "subskills.json"
    )
    parser.add_argument(
        "--sync-report", type=Path, default=SKILL_ROOT / "references" / "sync-report.json"
    )
    parser.add_argument(
        "--audit-report", type=Path, default=SKILL_ROOT / "references" / "audit-report.json"
    )
    parser.add_argument("--output", type=Path, default=SKILL_ROOT / "THIRD_PARTY_NOTICES.md")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    sync_report = json.loads(args.sync_report.read_text(encoding="utf-8"))
    audit_report = json.loads(args.audit_report.read_text(encoding="utf-8"))
    records = {record["id"]: record for record in sync_report["skills"]}
    missing_records = sorted(
        entry["id"] for entry in manifest["skills"] if entry["id"] not in records
    )
    if missing_records:
        raise ValueError(
            "Sync report is missing manifest entries: " + ", ".join(missing_records)
        )

    source_labels: dict[str, str] = {}
    for entry in manifest["skills"]:
        source_labels.setdefault(entry["source"], source_label(entry))
    evidence = {item["source"]: item for item in audit_report["license_evidence"]}
    missing_evidence = sorted(set(source_labels) - set(evidence))
    if missing_evidence:
        raise ValueError(
            "Audit report is missing source evidence: " + ", ".join(missing_evidence)
        )
    unknown_sources = [item for item in evidence.values() if item["status"] == "unknown"]
    declaration_sources = [
        item for item in evidence.values() if item["status"] == "declaration_only"
    ]
    licensed_sources = [
        item for item in evidence.values() if item["status"] == "license_text"
    ]

    lines = [
        "# Third-Party Notices",
        "",
        "Bundled sub-skills remain subject to their upstream licenses. Source",
        "revisions, recovery archives, copied legal files, and content adaptations",
        "and installer normalizations are recorded below. A recovery archive's",
        "license does not replace the",
        "original source's license. Content marked `UNKNOWN` must not be publicly",
        "redistributed until permission is confirmed. A declaration-only source",
        "requires verification and inclusion of its complete license terms.",
        "",
        "## Redistribution Review",
        "",
        f"- License text captured: {len(licensed_sources)} of {len(evidence)} sources",
        f"- Declaration only: {len(declaration_sources)} sources",
        f"- Unknown license: {len(unknown_sources)} sources",
        "",
        "### Unknown License",
        "",
    ]
    lines.extend(
        f"- [{source_labels[item['source']]}]({item['source']})"
        for item in sorted(unknown_sources, key=lambda item: item["source"])
    )
    lines.extend(["", "### Declaration Only", ""])
    lines.extend(
        f"- [{source_labels[item['source']]}]({item['source']}): "
        + ", ".join(f"`{license_name}`" for license_name in item["declared_licenses"])
        for item in sorted(declaration_sources, key=lambda item: item["source"])
    )
    lines.extend([
        "",
        "## Bundled Content",
        "",
        "| Sub-skill | Original source | Bundled content | Bundle hash | License status | Original license evidence | Recovery legal files | Adaptations / packaging |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for entry in manifest["skills"]:
        record = records[entry["id"]]
        original_cell = f"[{source_label(entry)}]({entry['source']})"
        content_source = record.get("recovery_source", entry["source"])
        revision = record.get("recovery_revision", record.get("source_head"))
        if revision:
            revision_cell = f"[{revision[:12]}]({content_source}/tree/{revision})"
        else:
            revision_cell = "not bundled"
        recovery_kind = record.get("recovery_kind")
        if recovery_kind:
            revision_cell = f"{recovery_kind}: {revision_cell}"
        recovery_path = record.get("recovery_path")
        if recovery_path:
            revision_cell += f"<br>`{recovery_path}`"
        digest = record.get("sha256", "not bundled")
        if digest != "not bundled":
            digest = f"`{digest[:16]}`"
        source_evidence = evidence[entry["source"]]
        original_license_files = sorted(
            {
                path
                for path in record.get("source_legal_files", [])
                if is_license_path(path)
            }
            | set(bundled_license_files(entry))
        )
        if original_license_files:
            original_legal = legal_cell(original_license_files)
        elif source_evidence["declared_licenses"]:
            original_legal = "Declared: " + ", ".join(
                f"`{license_name}`" for license_name in source_evidence["declared_licenses"]
            )
        else:
            original_legal = "**UNKNOWN**"
        license_status = source_evidence["status"].replace("_", " ")
        recovery_legal = record.get("recovery_legal_files", [])
        recovery_legal_cell = (
            legal_cell(recovery_legal) if recovery_kind and recovery_legal else "none"
        )
        adaptations = record.get("content_adaptations", [])
        packaging = record.get("install_excluded_files", [])
        adaptation_notes = list(adaptations)
        if packaging:
            omitted = ", ".join(f"`{path}`" for path in packaging)
            adaptation_notes.append(f"Skills CLI omits installer-reserved {omitted}.")
        adaptation_cell = "<br>".join(adaptation_notes) if adaptation_notes else "none"
        lines.append(
            f"| `{entry['id']}` | {original_cell} | {revision_cell} | {digest} | "
            f"{license_status} | {original_legal} | {recovery_legal_cell} | "
            f"{adaptation_cell} |"
        )
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(manifest['skills'])} notices to {args.output}")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""Load and validate the source-qualified CTO specialist catalog."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path


OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SKILL_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def valid_component(value: object, pattern: re.Pattern[str]) -> bool:
    return (
        isinstance(value, str)
        and value not in {".", ".."}
        and pattern.fullmatch(value) is not None
    )


def validate_manifest(manifest: object) -> dict:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("Unsupported sub-skill manifest schema")
    entries = manifest.get("skills")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Manifest skills must be a non-empty list")

    ids: list[str] = []
    names: Counter[str] = Counter()
    occurrences = 0
    providers: dict[str, list[str]] = defaultdict(list)
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Manifest entry {index} must be an object")
        owner = entry.get("owner")
        repository = entry.get("repository")
        skill = entry.get("skill")
        if not valid_component(owner, OWNER_PATTERN):
            raise ValueError(f"Unsafe catalog owner at entry {index}: {owner!r}")
        if not valid_component(repository, REPOSITORY_PATTERN):
            raise ValueError(
                f"Unsafe catalog repository at entry {index}: {repository!r}"
            )
        if not valid_component(skill, SKILL_PATTERN):
            raise ValueError(f"Unsafe catalog skill at entry {index}: {skill!r}")

        expected_id = f"{owner}/{repository}#{skill}"
        expected_source = f"https://github.com/{owner}/{repository}"
        if entry.get("id") != expected_id or entry.get("source") != expected_source:
            raise ValueError(f"Invalid catalog identity: {entry.get('id')!r}")
        contexts = entry.get("contexts", [])
        if not isinstance(contexts, list) or not all(
            isinstance(context, str) for context in contexts
        ):
            raise ValueError(f"Catalog contexts must be strings: {expected_id}")
        if "source_lines" in entry:
            raise ValueError(f"Catalog contains obsolete source-line metadata: {expected_id}")
        weight = entry.get("occurrences", 1)
        if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1:
            raise ValueError(f"Catalog occurrences must be positive: {expected_id}")

        ids.append(expected_id)
        names[skill] += 1
        occurrences += weight
        providers[skill].append(expected_id)

    if len(ids) != len(set(ids)):
        raise ValueError("Manifest contains duplicate source-qualified IDs")
    if ids != sorted(ids, key=str.lower):
        raise ValueError("Manifest entries are not deterministically ordered")

    collisions = {
        name: sorted(source_ids)
        for name, source_ids in sorted(providers.items())
        if len(source_ids) > 1
    }
    expected_summary = {
        "command_occurrences": occurrences,
        "unique_source_skill_pairs": len(entries),
        "unique_skill_names": len(names),
        "name_collision_count": len(collisions),
    }
    if manifest.get("summary") != expected_summary:
        raise ValueError("Manifest summary does not match catalog entries")
    if manifest.get("name_collisions") != collisions:
        raise ValueError("Manifest name collisions do not match catalog entries")
    return manifest


def load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read manifest {path}: {error}") from error
    return validate_manifest(manifest)


def safe_relative_path(value: str) -> bool:
    path = Path(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def validate_recovery(recovery: object, manifest: dict) -> dict:
    if not isinstance(recovery, dict) or recovery.get("schema_version") != 1:
        raise ValueError("Unsupported recovery schema")
    rules = recovery.get("recoveries")
    if not isinstance(rules, list):
        raise ValueError("Recovery rules must be a list")

    manifest_ids = {entry["id"] for entry in manifest["skills"]}
    recovery_ids: list[str] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"Recovery rule {index} must be an object")
        owner = rule.get("owner")
        repository = rule.get("repository")
        if not valid_component(owner, OWNER_PATTERN):
            raise ValueError(f"Unsafe recovery owner at rule {index}: {owner!r}")
        if not valid_component(repository, REPOSITORY_PATTERN):
            raise ValueError(
                f"Unsafe recovery repository at rule {index}: {repository!r}"
            )
        if rule.get("source") != f"https://github.com/{owner}/{repository}":
            raise ValueError(f"Invalid recovery source at rule {index}")
        if not isinstance(rule.get("revision"), str) or not REVISION_PATTERN.fullmatch(
            rule["revision"]
        ):
            raise ValueError(f"Recovery revision must be a full commit at rule {index}")
        if not isinstance(rule.get("reason"), str) or not rule["reason"].strip():
            raise ValueError(f"Recovery reason is required at rule {index}")

        kind = rule.get("kind", "historical")
        if kind not in {"historical", "legacy", "mirror", "successor"}:
            raise ValueError(f"Unsupported recovery kind at rule {index}: {kind!r}")
        archive_owner = rule.get("archive_owner")
        archive_repository = rule.get("archive_repository")
        if (archive_owner is None) != (archive_repository is None):
            raise ValueError(f"Recovery archive coordinates must be paired at rule {index}")
        if kind in {"mirror", "successor"}:
            if not valid_component(archive_owner, OWNER_PATTERN) or not valid_component(
                archive_repository, REPOSITORY_PATTERN
            ):
                raise ValueError(f"Invalid recovery archive at rule {index}")

        skills = rule.get("skills")
        if not isinstance(skills, list) or not skills:
            raise ValueError(f"Recovery skills must be a non-empty list at rule {index}")
        if len(skills) != len(set(skills)):
            raise ValueError(f"Recovery rule contains duplicate skills at rule {index}")
        template = rule.get("path_template")
        if not isinstance(template, str):
            raise ValueError(f"Recovery path template is required at rule {index}")
        upstream_template = rule.get("upstream_skill_path_template")
        if upstream_template is not None and not isinstance(upstream_template, str):
            raise ValueError(f"Invalid upstream path template at rule {index}")

        for skill in skills:
            if not valid_component(skill, SKILL_PATTERN):
                raise ValueError(f"Unsafe recovery skill at rule {index}: {skill!r}")
            try:
                rendered_path = template.format(skill=skill)
                rendered_upstream = (
                    upstream_template.format(skill=skill)
                    if upstream_template is not None
                    else rendered_path
                )
            except (KeyError, ValueError) as error:
                raise ValueError(f"Invalid recovery path template at rule {index}") from error
            if not safe_relative_path(rendered_path) or not safe_relative_path(
                rendered_upstream
            ):
                raise ValueError(f"Unsafe recovery path at rule {index}")
            recovery_id = f"{owner}/{repository}#{skill}"
            if recovery_id not in manifest_ids:
                raise ValueError(f"Recovery is not in the manifest: {recovery_id}")
            recovery_ids.append(recovery_id)

        legacy = rule.get("legacy_markdown", False)
        if not isinstance(legacy, bool) or not isinstance(
            rule.get("skill_file_only", False), bool
        ):
            raise ValueError(f"Recovery flags must be boolean at rule {index}")
        if kind == "legacy" and (
            not legacy
            or not isinstance(rule.get("frontmatter_description"), str)
            or not rule["frontmatter_description"].strip()
        ):
            raise ValueError(f"Legacy recovery metadata is incomplete at rule {index}")

    if len(recovery_ids) != len(set(recovery_ids)):
        raise ValueError("Recovery catalog contains duplicate source-qualified IDs")
    return recovery


def load_recovery(path: Path, manifest: dict) -> dict:
    try:
        recovery = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read recovery catalog {path}: {error}") from error
    return validate_recovery(recovery, manifest)
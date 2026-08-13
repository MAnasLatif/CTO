#!/usr/bin/env python3
"""Download CTO sub-skills into source-qualified bundle directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = SKILL_ROOT / "references" / "subskills.json"
DEFAULT_REPORT = SKILL_ROOT / "references" / "sync-report.json"
DEFAULT_RECOVERY = SKILL_ROOT / "references" / "recovery.json"
LEGAL_PREFIXES = ("license", "copying", "notice", "authors")
COMMON_LEGAL_FILES = (
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
    "LICENCE",
    "LICENCE.md",
    "LICENCE.txt",
    "COPYING",
    "COPYING.md",
    "COPYING.txt",
    "NOTICE",
    "NOTICE.md",
    "NOTICE.txt",
    "AUTHORS",
    "AUTHORS.md",
)
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_RECOVERED_BYTES = 50 * 1024 * 1024
INSTALLER_EXCLUDED_FILES = frozenset({"metadata.json"})
SKILLS_CLI_PACKAGE = os.environ.get("CTO_SKILLS_CLI_PACKAGE", "skills@1.5.22")


def source_key(entry: dict) -> str:
    return f"{entry['owner']}--{entry['repository']}"


def tree_digest(
    directory: Path, excluded_files: set[str] | frozenset[str] = frozenset()
) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    file_count = 0
    byte_count = 0
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
        file_count += 1
        byte_count += len(data)
    return digest.hexdigest(), file_count, byte_count


def attach_install_digest(record: dict, directory: Path) -> None:
    excluded_files = sorted(
        relative
        for relative in INSTALLER_EXCLUDED_FILES
        if (directory / relative).is_file()
    )
    if not excluded_files:
        return
    digest, files, size = tree_digest(directory, set(excluded_files))
    record["install_sha256"] = digest
    record["install_files"] = files
    record["install_bytes"] = size
    record["install_excluded_files"] = excluded_files


def remote_head(source: str) -> str | None:
    result = subprocess.run(
        ["git", "ls-remote", source, "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.split()[0]


def lock_metadata(workspace: Path, skill: str) -> dict:
    lock_file = workspace / "skills-lock.json"
    if not lock_file.exists():
        return {}
    try:
        entry = json.loads(lock_file.read_text(encoding="utf-8"))["skills"][skill]
    except (KeyError, OSError, json.JSONDecodeError):
        return {}
    return {
        "upstream_skill_path": entry.get("skillPath"),
        "upstream_computed_hash": entry.get("computedHash"),
    }


def github_api_json(path: str) -> object | None:
    gh = shutil.which("gh")
    if gh:
        result = subprocess.run(
            [gh, "api", path], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                pass

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "cto-skill-bundler",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/{path}", headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError):
        return None


def retained_source_legal_files(entry: dict) -> list[str]:
    source_directory = SKILL_ROOT / "subskills" / source_key(entry) / "_source"
    if not source_directory.exists():
        return []
    return sorted(
        str(path.relative_to(SKILL_ROOT))
        for path in source_directory.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.name.lower().startswith(LEGAL_PREFIXES)
    )


def fetch_source_legal_files(entry: dict, head: str | None) -> list[str]:
    if not head:
        return retained_source_legal_files(entry)
    api_path = (
        f"repos/{entry['owner']}/{entry['repository']}/contents?"
        + urllib.parse.urlencode({"ref": head})
    )
    listing = github_api_json(api_path)
    if not isinstance(listing, list):
        listing = []

    candidates = {
        str(item.get("name", "")): item.get("download_url")
        for item in listing
        if str(item.get("name", "")).lower().startswith(LEGAL_PREFIXES)
        and item.get("download_url")
    }
    if not listing:
        raw_root = (
            "https://raw.githubusercontent.com/"
            f"{urllib.parse.quote(entry['owner'], safe='')}/"
            f"{urllib.parse.quote(entry['repository'], safe='')}/"
            f"{urllib.parse.quote(head, safe='')}"
        )
        candidates.update(
            {
                name: f"{raw_root}/{urllib.parse.quote(name, safe='')}"
                for name in COMMON_LEGAL_FILES
            }
        )

    source_directory = SKILL_ROOT / "subskills" / source_key(entry) / "_source" / head
    source_directory.mkdir(parents=True, exist_ok=True)
    fetched_legal_files: list[str] = []
    for name, download_url in candidates.items():
        request = urllib.request.Request(
            download_url, headers={"User-Agent": "cto-skill-bundler"}
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read(2_000_001)
        except (OSError, urllib.error.HTTPError):
            continue
        if len(data) > 2_000_000:
            continue
        output = source_directory / name
        output.write_bytes(data)
        fetched_legal_files.append(str(output.relative_to(SKILL_ROOT)))

    revision_legal_files = sorted(
        str(path.relative_to(SKILL_ROOT))
        for path in source_directory.iterdir()
        if path.is_file()
        and not path.is_symlink()
        and path.name.lower().startswith(LEGAL_PREFIXES)
    )

    metadata_file = source_directory / "SOURCE.json"
    metadata_file.write_text(
        json.dumps(
            {
                "source": entry["source"],
                "revision": head,
                "legal_files": revision_legal_files,
                "fetched_legal_files": sorted(fetched_legal_files),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return retained_source_legal_files(entry)


def recovery_index(recovery: dict) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for rule in recovery.get("recoveries", []):
        for skill in rule["skills"]:
            entry_id = f"{rule['owner']}/{rule['repository']}#{skill}"
            indexed[entry_id] = {
                **rule,
                "skill": skill,
                "path": rule["path_template"].format(skill=skill).strip("/"),
            }
    return indexed


def archive_identity(rule: dict) -> tuple[str, str, str]:
    return (
        rule.get("archive_owner", rule["owner"]),
        rule.get("archive_repository", rule["repository"]),
        rule["revision"],
    )


def archive_entry(rule: dict) -> dict:
    owner, repository, _ = archive_identity(rule)
    return {
        "owner": owner,
        "repository": repository,
        "source": rule.get("archive_source", f"https://github.com/{owner}/{repository}"),
    }


def recovery_metadata(source: str, rule: dict) -> dict:
    archive = archive_entry(rule)
    upstream_template = rule.get("upstream_skill_path_template")
    if upstream_template:
        upstream_path = upstream_template.format(skill=rule["skill"])
    elif rule.get("legacy_markdown"):
        upstream_path = rule["path"]
    else:
        upstream_path = f"{rule['path']}/SKILL.md"
    return {
        "source": source,
        "source_head": rule["revision"],
        "upstream_skill_path": upstream_path,
        "recovery_kind": rule.get(
            "kind", "historical" if archive["source"] == source else "mirror"
        ),
        "recovery_source": archive["source"],
        "recovery_revision": rule["revision"],
        "recovery_path": rule["path"],
        "recovery_reason": rule["reason"],
    }


def download_archive(rule: dict, destination: Path) -> None:
    owner, repository, revision = archive_identity(rule)
    url = (
        f"https://api.github.com/repos/{owner}/{repository}"
        f"/tarball/{revision}"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "cto-skill-bundler",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        with destination.open("wb") as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError(f"Archive exceeds {MAX_ARCHIVE_BYTES} bytes")
                output.write(chunk)


def download_recovery_file(rule: dict, path: str) -> bytes:
    owner, repository, revision = archive_identity(rule)
    encoded_path = urllib.parse.quote(path, safe="/")
    url = (
        "https://raw.githubusercontent.com/"
        f"{urllib.parse.quote(owner, safe='')}/"
        f"{urllib.parse.quote(repository, safe='')}/"
        f"{urllib.parse.quote(revision, safe='')}/{encoded_path}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "cto-skill-bundler"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read(MAX_RECOVERED_BYTES + 1)
            break
        except urllib.error.HTTPError as error:
            if error.code != 429 and error.code < 500:
                raise
            if attempt == 2:
                raise
    if len(data) > MAX_RECOVERED_BYTES:
        raise ValueError(f"Recovered file exceeds {MAX_RECOVERED_BYTES} bytes")
    return data


def attach_recovery_legal_files(
    records: dict[str, dict], representative: dict, original_entry: dict
) -> None:
    archive_owner, archive_repository, revision = archive_identity(representative)
    legal_files = fetch_source_legal_files(archive_entry(representative), revision)
    same_source = (
        archive_owner.lower() == original_entry["owner"].lower()
        and archive_repository.lower() == original_entry["repository"].lower()
    )
    for record in records.values():
        if same_source:
            record["source_legal_files"] = legal_files
        else:
            record["recovery_legal_files"] = legal_files


def recover_direct_files(
    source: str,
    applicable: list[dict],
    recoveries: dict[str, dict],
    force: bool,
) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for entry in applicable:
        rule = recoveries[entry["id"]]
        destination = SKILL_ROOT / "subskills" / source_key(entry) / entry["skill"]
        if destination.exists():
            if not force:
                digest, files, size = tree_digest(destination)
                record = {
                    "id": entry["id"],
                    "status": "existing",
                    "path": str(destination.relative_to(SKILL_ROOT)),
                    "sha256": digest,
                    "files": files,
                    "bytes": size,
                }
                record.update(recovery_metadata(source, rule))
                if rule.get("legacy_markdown"):
                    record["content_adaptations"] = [
                        "Prepended required Agent Skills frontmatter to legacy Markdown source."
                    ]
                records[entry["id"]] = record
                continue
            shutil.rmtree(destination)

        archived_path = (
            rule["path"]
            if rule.get("legacy_markdown")
            else f"{rule['path']}/SKILL.md"
        )
        try:
            data = download_recovery_file(rule, archived_path)
        except (OSError, ValueError) as error:
            records[entry["id"]] = {
                "id": entry["id"],
                "status": "failed",
                "error": str(error),
            }
            continue

        if rule.get("legacy_markdown"):
            description = rule["frontmatter_description"]
            frontmatter = (
                "---\n"
                f"name: {entry['skill']}\n"
                f"description: {json.dumps(description, ensure_ascii=True)}\n"
                "---\n\n"
            ).encode("utf-8")
            data = frontmatter + data

        destination.mkdir(parents=True, exist_ok=True)
        (destination / "SKILL.md").write_bytes(data)
        digest, files, size = tree_digest(destination)
        record = {
            "id": entry["id"],
            "status": "recovered",
            "path": str(destination.relative_to(SKILL_ROOT)),
            "sha256": digest,
            "files": files,
            "bytes": size,
        }
        record.update(recovery_metadata(source, rule))
        if rule.get("legacy_markdown"):
            record["content_adaptations"] = [
                "Prepended required Agent Skills frontmatter to legacy Markdown source."
            ]
        records[entry["id"]] = record

    attach_recovery_legal_files(records, recoveries[applicable[0]["id"]], applicable[0])
    return records


def recover_from_archive(
    source: str,
    entries: list[dict],
    recoveries: dict[str, dict],
    force: bool,
) -> dict[str, dict]:
    applicable = [entry for entry in entries if entry["id"] in recoveries]
    if not applicable:
        return {}
    if all(
        recoveries[entry["id"]].get("skill_file_only")
        or recoveries[entry["id"]].get("legacy_markdown")
        for entry in applicable
    ):
        return recover_direct_files(source, applicable, recoveries, force)

    archives = {archive_identity(recoveries[entry["id"]]) for entry in applicable}
    if len(archives) != 1:
        raise ValueError(f"Recovery for {source} must use one archive per sync")
    archive_owner, archive_repository, revision = archives.pop()
    representative = recoveries[applicable[0]["id"]]

    with tempfile.TemporaryDirectory(prefix="cto-recovery-") as temporary:
        archive = Path(temporary) / "source.tar.gz"
        download_archive(representative, archive)
        records: dict[str, dict] = {}
        total_recovered = 0
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for entry in applicable:
                rule = recoveries[entry["id"]]
                path_parts = Path(rule["path"]).parts
                matching = []
                for member in members:
                    member_parts = Path(member.name).parts
                    archived_parts = tuple(member_parts[1:])
                    if rule.get("legacy_markdown"):
                        matches = archived_parts == path_parts
                    else:
                        matches = archived_parts[: len(path_parts)] == path_parts
                    if matches:
                        matching.append(member)

                destination = SKILL_ROOT / "subskills" / source_key(entry) / entry["skill"]
                if destination.exists():
                    if not force:
                        digest, files, size = tree_digest(destination)
                        records[entry["id"]] = {
                            "id": entry["id"],
                            "status": "existing",
                            "path": str(destination.relative_to(SKILL_ROOT)),
                            "sha256": digest,
                            "files": files,
                            "bytes": size,
                        }
                        records[entry["id"]].update(recovery_metadata(source, rule))
                        continue
                    shutil.rmtree(destination)

                regular_files = [member for member in matching if member.isfile()]
                if rule.get("legacy_markdown"):
                    valid_source = len(regular_files) == 1
                else:
                    valid_source = any(
                        Path(member.name).name == "SKILL.md" for member in regular_files
                    )
                if not valid_source:
                    records[entry["id"]] = {
                        "id": entry["id"],
                        "status": "failed",
                        "error": f"No recoverable skill at {rule['path']} in {revision}",
                    }
                    continue

                if rule.get("legacy_markdown"):
                    member = regular_files[0]
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        raise ValueError(f"Could not read {rule['path']} from archive")
                    data = extracted.read(MAX_RECOVERED_BYTES + 1)
                    total_recovered += len(data)
                    if len(data) > MAX_RECOVERED_BYTES or total_recovered > MAX_RECOVERED_BYTES:
                        raise ValueError("Recovered content exceeds safety limit")
                    description = rule["frontmatter_description"]
                    frontmatter = (
                        "---\n"
                        f"name: {entry['skill']}\n"
                        f"description: {json.dumps(description, ensure_ascii=True)}\n"
                        "---\n\n"
                    ).encode("utf-8")
                    output = destination / "SKILL.md"
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(frontmatter + data)
                    output.chmod(member.mode & 0o777)
                else:
                    for member in regular_files:
                        relative_parts = Path(member.name).parts[1 + len(path_parts) :]
                        if not relative_parts or ".." in relative_parts:
                            continue
                        if rule.get("skill_file_only") and relative_parts != ("SKILL.md",):
                            continue
                        extracted = tar.extractfile(member)
                        if extracted is None:
                            continue
                        data = extracted.read(MAX_RECOVERED_BYTES + 1)
                        total_recovered += len(data)
                        if len(data) > MAX_RECOVERED_BYTES or total_recovered > MAX_RECOVERED_BYTES:
                            raise ValueError("Recovered content exceeds safety limit")
                        output = destination.joinpath(*relative_parts)
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(data)
                        output.chmod(member.mode & 0o777)

                digest, files, size = tree_digest(destination)
                records[entry["id"]] = {
                    "id": entry["id"],
                    "status": "recovered",
                    "path": str(destination.relative_to(SKILL_ROOT)),
                    "sha256": digest,
                    "files": files,
                    "bytes": size,
                }
                records[entry["id"]].update(recovery_metadata(source, rule))
                if rule.get("legacy_markdown"):
                    records[entry["id"]]["content_adaptations"] = [
                        "Prepended required Agent Skills frontmatter to legacy Markdown source."
                    ]

    attach_recovery_legal_files(records, representative, applicable[0])
    return records


def run_install(source: str, skills: list[str], workspace: Path) -> subprocess.CompletedProcess:
    command = [
        "npx", "--yes", SKILLS_CLI_PACKAGE, "add", source,
        "--agent", "github-copilot", "-y", "--copy", "--full-depth",
    ]
    for skill in skills:
        command.extend(["--skill", skill])
    return subprocess.run(
        command,
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def copy_installed(entry: dict, workspace: Path, force: bool) -> dict:
    installed = workspace / ".agents" / "skills" / entry["skill"]
    destination = SKILL_ROOT / "subskills" / source_key(entry) / entry["skill"]
    if not (installed / "SKILL.md").exists():
        return {"id": entry["id"], "status": "missing", "error": "CLI produced no SKILL.md"}

    if destination.exists():
        if not force:
            digest, files, size = tree_digest(destination)
            record = {
                "id": entry["id"],
                "status": "existing",
                "path": str(destination.relative_to(SKILL_ROOT)),
                "sha256": digest,
                "files": files,
                "bytes": size,
            }
            record.update(lock_metadata(workspace, entry["skill"]))
            return record
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(installed, destination, symlinks=False)
    digest, files, size = tree_digest(destination)
    record = {
        "id": entry["id"],
        "status": "downloaded",
        "path": str(destination.relative_to(SKILL_ROOT)),
        "sha256": digest,
        "files": files,
        "bytes": size,
    }
    record.update(lock_metadata(workspace, entry["skill"]))
    return record


def sync_source(
    source: str,
    entries: list[dict],
    force: bool,
    recoveries: dict[str, dict],
) -> list[dict]:
    head = remote_head(source)
    with tempfile.TemporaryDirectory(prefix="cto-subskills-") as temporary:
        workspace = Path(temporary)
        result = run_install(source, [entry["skill"] for entry in entries], workspace)
        if result.returncode == 0:
            records = [copy_installed(entry, workspace, force) for entry in entries]
        else:
            records = []
            # One stale name should not prevent valid siblings from being bundled.
            for entry in entries:
                with tempfile.TemporaryDirectory(prefix="cto-subskill-") as retry:
                    retry_workspace = Path(retry)
                    retry_result = run_install(source, [entry["skill"]], retry_workspace)
                    if retry_result.returncode == 0:
                        record = copy_installed(entry, retry_workspace, force)
                    else:
                        error_output = (retry_result.stderr or retry_result.stdout).strip()
                        record = {
                            "id": entry["id"],
                            "status": "failed",
                            "error": error_output[-2000:],
                        }
                    records.append(record)
        unresolved = [
            entry
            for entry, record in zip(entries, records)
            if record["status"] in {"failed", "missing"}
        ]
        recovered = recover_from_archive(source, unresolved, recoveries, force)
        records = [recovered.get(record["id"], record) for record in records]

        legal_files = fetch_source_legal_files(entries[0], head)
        for record in records:
            record["source"] = source
            record["source_current_head"] = head
            if record.get("path"):
                attach_install_digest(record, SKILL_ROOT / record["path"])
            if record["id"] in recovered:
                if legal_files:
                    record["source_legal_files"] = sorted(
                        set(record.get("source_legal_files", [])) | set(legal_files)
                    )
                else:
                    record.setdefault("source_legal_files", [])
            else:
                record["source_head"] = head
                record["source_legal_files"] = legal_files
        return records


def select_entries(manifest: dict, selectors: list[str]) -> list[dict]:
    if not selectors:
        return manifest["skills"]
    wanted = set(selectors)
    selected = [
        entry
        for entry in manifest["skills"]
        if entry["id"] in wanted or entry["skill"] in wanted
    ]
    matched = {entry["id"] for entry in selected} | {entry["skill"] for entry in selected}
    missing = sorted(wanted - matched)
    if missing:
        raise ValueError(f"Unknown selectors: {', '.join(missing)}")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--recovery", type=Path, default=DEFAULT_RECOVERY)
    parser.add_argument("--only", action="append", default=[], help="Skill name or source-qualified ID")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--force", action="store_true", help="Replace existing bundled copies")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    recovery = (
        json.loads(args.recovery.read_text(encoding="utf-8"))
        if args.recovery.exists()
        else {"recoveries": []}
    )
    recoveries = recovery_index(recovery)
    entries = select_entries(manifest, args.only)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        grouped[entry["source"]].append(entry)

    if args.dry_run:
        print(f"Would sync {len(entries)} skills from {len(grouped)} repositories")
        for source, source_entries in sorted(grouped.items()):
            print(f"{source}: {', '.join(entry['skill'] for entry in source_entries)}")
        return

    all_records: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(args.jobs, 1)) as executor:
        futures = {
            executor.submit(sync_source, source, source_entries, args.force, recoveries): source
            for source, source_entries in grouped.items()
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                records = future.result()
            except Exception as error:  # Keep other independent sources progressing.
                records = [
                    {
                        "id": entry["id"],
                        "source": source,
                        "source_head": None,
                        "status": "failed",
                        "error": str(error),
                    }
                    for entry in grouped[source]
                ]
            all_records.extend(records)
            complete = sum(
                record["status"] in {"downloaded", "existing", "recovered"}
                for record in records
            )
            print(f"[{complete}/{len(records)}] {source}")

    all_records.sort(key=lambda record: record["id"].lower())
    counts: dict[str, int] = defaultdict(int)
    for record in all_records:
        counts[record["status"]] += 1
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested": len(entries),
        "repositories": len(grouped),
        "status_counts": dict(sorted(counts.items())),
        "skills": all_records,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["status_counts"], sort_keys=True))

    failures = sum(counts[key] for key in ("failed", "missing"))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
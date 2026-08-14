from __future__ import annotations

import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPOSITORY_ROOT / "skills" / "cto"
SCRIPT_ROOT = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from catalog import load_manifest, validate_manifest, validate_recovery


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_ROOT / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CatalogSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_manifest(SKILL_ROOT / "references" / "subskills.json")

    def test_rejects_traversal_skill(self) -> None:
        manifest = json.loads(json.dumps(self.manifest))
        entry = manifest["skills"][0]
        entry["skill"] = "../escape"
        entry["id"] = f"{entry['owner']}/{entry['repository']}#../escape"

        with self.assertRaisesRegex(ValueError, "Unsafe catalog skill"):
            validate_manifest(manifest)

    def test_rejects_traversal_recovery_path(self) -> None:
        recovery = json.loads(
            (SKILL_ROOT / "references" / "recovery.json").read_text(encoding="utf-8")
        )
        recovery["recoveries"][0]["path_template"] = "../{skill}"

        with self.assertRaisesRegex(ValueError, "Unsafe recovery path"):
            validate_recovery(recovery, self.manifest)


class SyncIntegrityTests(unittest.TestCase):
    def test_existing_divergent_payload_is_stale(self) -> None:
        sync = load_script("sync_subskills")
        with tempfile.TemporaryDirectory(prefix="cto-sync-test-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            skill_root = root / "bundle"
            entry = {
                "id": "example/repo#demo",
                "owner": "example",
                "repository": "repo",
                "skill": "demo",
            }
            installed = workspace / ".agents" / "skills" / "demo"
            destination = skill_root / "subskills" / "example--repo" / "demo"
            installed.mkdir(parents=True)
            destination.mkdir(parents=True)
            (installed / "SKILL.md").write_text("new content\n", encoding="utf-8")
            (destination / "SKILL.md").write_text("old content\n", encoding="utf-8")

            with patch.object(sync, "SKILL_ROOT", skill_root):
                record = sync.copy_installed(entry, workspace, False)

            self.assertEqual(record["status"], "stale")
            self.assertNotEqual(record["sha256"], record["upstream_sha256"])
            self.assertNotIn("source_head", record)

    def test_existing_recovery_payloads_are_compared(self) -> None:
        sync = load_script("sync_subskills")
        entry = {
            "id": "example/repo#demo",
            "source": "https://github.com/example/repo",
            "owner": "example",
            "repository": "repo",
            "skill": "demo",
        }
        base_rule = {
            "owner": "example",
            "repository": "repo",
            "source": entry["source"],
            "revision": "a" * 40,
            "path": "skills/demo",
            "path_template": "skills/{skill}",
            "reason": "test",
            "skill": "demo",
        }
        with tempfile.TemporaryDirectory(prefix="cto-recovery-test-") as temporary:
            root = Path(temporary)
            skill_root = root / "bundle"
            destination = skill_root / "subskills" / "example--repo" / "demo"
            destination.mkdir(parents=True)
            (destination / "SKILL.md").write_text("old\n", encoding="utf-8")

            direct_rule = {**base_rule, "skill_file_only": True}
            with patch.object(sync, "SKILL_ROOT", skill_root), patch.object(
                sync, "download_recovery_file", return_value=b"new\n"
            ), patch.object(sync, "attach_recovery_legal_files"):
                direct = sync.recover_direct_files(
                    entry["source"], [entry], {entry["id"]: direct_rule}, False
                )[entry["id"]]
            self.assertEqual(direct["status"], "stale")

            archive = root / "fixture.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                data = b"new\n"
                member = tarfile.TarInfo("repo-commit/skills/demo/SKILL.md")
                member.size = len(data)
                output.addfile(member, io.BytesIO(data))

            def copy_archive(_rule: dict, target: Path) -> None:
                shutil.copyfile(archive, target)

            with patch.object(sync, "SKILL_ROOT", skill_root), patch.object(
                sync, "download_archive", side_effect=copy_archive
            ), patch.object(sync, "attach_recovery_legal_files"):
                archived = sync.recover_from_archive(
                    entry["source"], [entry], {entry["id"]: base_rule}, False
                )[entry["id"]]
            self.assertEqual(archived["status"], "stale")
            self.assertNotEqual(archived["sha256"], archived["upstream_sha256"])

    def test_source_change_during_sync_is_unverified(self) -> None:
        sync = load_script("sync_subskills")
        entry = {
            "id": "example/repo#demo",
            "source": "https://github.com/example/repo",
            "owner": "example",
            "repository": "repo",
            "skill": "demo",
        }
        with tempfile.TemporaryDirectory(prefix="cto-head-test-") as temporary:
            skill_root = Path(temporary) / "bundle"

            def install(_source: str, _skills: list[str], workspace: Path):
                installed = workspace / ".agents" / "skills" / "demo"
                installed.mkdir(parents=True)
                (installed / "SKILL.md").write_text(
                    "---\nname: demo\ndescription: demo\n---\n", encoding="utf-8"
                )
                return subprocess.CompletedProcess([], 0)

            with patch.object(sync, "SKILL_ROOT", skill_root), patch.object(
                sync, "remote_head", side_effect=["a" * 40, "b" * 40]
            ), patch.object(sync, "run_install", side_effect=install), patch.object(
                sync, "fetch_source_legal_files", return_value=[]
            ):
                record = sync.sync_source(entry["source"], [entry], False, {})[0]

            self.assertEqual(record["status"], "unverified")
            self.assertNotIn("source_head", record)
            self.assertIn("changed during synchronization", record["error"])


class InstallerWorkflowTests(unittest.TestCase):
    def test_full_sync_generates_notices_after_validation(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "repository_installer", REPOSITORY_ROOT / "scripts" / "install.py"
        )
        if spec is None or spec.loader is None:
            self.fail("Could not load repository installer")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)

        with tempfile.TemporaryDirectory(prefix="cto-installer-test-") as temporary:
            root = Path(temporary)
            skill_root = root / "skills" / "cto"
            references = skill_root / "references"
            references.mkdir(parents=True)
            (references / "audit-report.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "installed_skills": 193,
                            "sources_with_unknown_license": 9,
                            "sources_with_declarations_only": 5,
                        }
                    }
                ),
                encoding="utf-8",
            )
            commands: list[list[str]] = []
            arguments = [
                "install.py",
                "--sync-only",
                "--acknowledge-third-party-sources",
            ]
            with patch.object(installer, "REPOSITORY_ROOT", root), patch.object(
                installer, "SKILL_ROOT", skill_root
            ), patch.object(installer, "require_commands"), patch.object(
                installer.subprocess, "run"
            ), patch.object(
                installer, "run", side_effect=lambda command: commands.append(command)
            ), patch.object(sys, "argv", arguments), redirect_stdout(io.StringIO()):
                installer.main()

            self.assertEqual(
                [Path(command[1]).name for command in commands],
                ["validate_bundle.py", "generate_notices.py"],
            )

    def test_wrapper_install_runs_in_target_workspace(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "targeted_installer", REPOSITORY_ROOT / "scripts" / "install.py"
        )
        if spec is None or spec.loader is None:
            self.fail("Could not load repository installer")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)

        with tempfile.TemporaryDirectory(prefix="cto-target-test-") as temporary:
            target = Path(temporary)
            calls: list[tuple[list[str], Path]] = []
            arguments = [
                "install.py",
                "--wrapper-only",
                "--agent",
                "github-copilot",
                "--target",
                str(target),
            ]
            with patch.object(installer, "require_commands"), patch.object(
                installer,
                "run",
                side_effect=lambda command, **kwargs: calls.append(
                    (command, kwargs.get("cwd", installer.REPOSITORY_ROOT))
                ),
            ), patch.object(sys, "argv", arguments):
                installer.main()

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], target.resolve())


class ProvenanceAuditTests(unittest.TestCase):
    def test_installed_skill_requires_sync_record(self) -> None:
        validator = load_script("validate_bundle")
        with tempfile.TemporaryDirectory(prefix="cto-audit-test-") as temporary:
            root = Path(temporary) / "skill"
            skill_directory = root / "subskills" / "example--repo" / "demo"
            references = root / "references"
            skill_directory.mkdir(parents=True)
            references.mkdir(parents=True)
            (skill_directory / "SKILL.md").write_text(
                "---\nname: demo\ndescription: demo\n---\n", encoding="utf-8"
            )
            manifest = {
                "schema_version": 1,
                "summary": {
                    "command_occurrences": 1,
                    "unique_source_skill_pairs": 1,
                    "unique_skill_names": 1,
                    "name_collision_count": 0,
                },
                "name_collisions": {},
                "skills": [
                    {
                        "id": "example/repo#demo",
                        "source": "https://github.com/example/repo",
                        "owner": "example",
                        "repository": "repo",
                        "skill": "demo",
                        "occurrences": 1,
                        "contexts": [],
                    }
                ],
            }
            manifest_path = references / "subskills.json"
            report_path = references / "sync-report.json"
            output_path = references / "audit-report.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report_path.write_text('{"skills": []}', encoding="utf-8")

            arguments = [
                "validate_bundle.py",
                "--manifest",
                str(manifest_path),
                "--sync-report",
                str(report_path),
                "--output",
                str(output_path),
            ]
            with patch.object(validator, "SKILL_ROOT", root), patch.object(
                sys, "argv", arguments
            ), self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
                validator.main()

            audit = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(audit["missing_sync_records"], ["example/repo#demo"])

    def test_matching_hash_requires_complete_source_metadata(self) -> None:
        validator = load_script("validate_bundle")
        with tempfile.TemporaryDirectory(prefix="cto-metadata-test-") as temporary:
            root = Path(temporary) / "skill"
            skill_directory = root / "subskills" / "example--repo" / "demo"
            references = root / "references"
            skill_directory.mkdir(parents=True)
            references.mkdir(parents=True)
            (skill_directory / "SKILL.md").write_text(
                "---\nname: demo\ndescription: demo\n---\n", encoding="utf-8"
            )
            manifest = {
                "schema_version": 1,
                "summary": {
                    "command_occurrences": 1,
                    "unique_source_skill_pairs": 1,
                    "unique_skill_names": 1,
                    "name_collision_count": 0,
                },
                "name_collisions": {},
                "skills": [
                    {
                        "id": "example/repo#demo",
                        "source": "https://github.com/example/repo",
                        "owner": "example",
                        "repository": "repo",
                        "skill": "demo",
                        "occurrences": 1,
                        "contexts": [],
                    }
                ],
            }
            manifest_path = references / "subskills.json"
            report_path = references / "sync-report.json"
            output_path = references / "audit-report.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(validator, "SKILL_ROOT", root):
                digest = validator.tree_digest(skill_directory)
            report_path.write_text(
                json.dumps(
                    {
                        "skills": [
                            {
                                "id": "example/repo#demo",
                                "status": "existing",
                                "path": "subskills/example--repo/demo",
                                "source_head": "a" * 40,
                                "sha256": digest,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            arguments = [
                "validate_bundle.py",
                "--manifest",
                str(manifest_path),
                "--sync-report",
                str(report_path),
                "--output",
                str(output_path),
            ]
            with patch.object(validator, "SKILL_ROOT", root), patch.object(
                sys, "argv", arguments
            ), self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
                validator.main()

            audit = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(audit["summary"]["invalid_sync_records"], 1)


if __name__ == "__main__":
    unittest.main()
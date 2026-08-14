#!/usr/bin/env python3
"""Synchronize the CTO specialist pack and install the skill locally."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPOSITORY_ROOT / "skills" / "cto"
DEFAULT_SKILLS_CLI_PACKAGE = os.environ.get(
    "CTO_SKILLS_CLI_PACKAGE", "skills@1.5.22"
)


def run(command: list[str], *, cwd: Path = REPOSITORY_ROOT) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def require_commands(commands: tuple[str, ...]) -> None:
    missing = [command for command in commands if shutil.which(command) is None]
    if missing:
        raise SystemExit("Missing required commands: " + ", ".join(missing))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent",
        action="append",
        default=[],
        help="Target agent accepted by the Skills CLI; repeat for multiple agents.",
    )
    parser.add_argument("--jobs", type=int, default=3, help="Parallel source syncs.")
    parser.add_argument(
        "--force-sync", action="store_true", help="Replace existing local sub-skills."
    )
    parser.add_argument(
        "--wrapper-only",
        action="store_true",
        help="Install only the MIT-licensed CTO wrapper without third-party payloads.",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Synchronize and validate specialists without installing the CTO skill.",
    )
    parser.add_argument(
        "--acknowledge-third-party-sources",
        action="store_true",
        help="Acknowledge that synchronized specialists use separate upstream terms.",
    )
    parser.add_argument(
        "--skills-cli-package",
        default=DEFAULT_SKILLS_CLI_PACKAGE,
        help="Pinned npm package used to run the Skills CLI.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Workspace where the CTO skill will be installed (default: current directory).",
    )
    args = parser.parse_args()

    if args.wrapper_only and args.sync_only:
        parser.error("--wrapper-only and --sync-only cannot be combined")
    if not args.sync_only and not args.agent:
        parser.error("provide at least one --agent")
    if not args.wrapper_only and not args.acknowledge_third_party_sources:
        parser.error(
            "full synchronization requires --acknowledge-third-party-sources"
        )
    target = args.target.expanduser().resolve()
    if not target.is_dir():
        parser.error(f"target workspace is not a directory: {target}")

    require_commands(("npx",))
    if not args.wrapper_only:
        require_commands(("git",))
        sync_command = [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "sync_subskills.py"),
            "--jobs",
            str(max(args.jobs, 1)),
        ]
        if args.force_sync:
            sync_command.append("--force")
        environment = os.environ.copy()
        environment["CTO_SKILLS_CLI_PACKAGE"] = args.skills_cli_package
        print("+ " + " ".join(sync_command), flush=True)
        subprocess.run(
            sync_command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            check=True,
        )
        run([sys.executable, str(SKILL_ROOT / "scripts" / "validate_bundle.py")])
        run([sys.executable, str(SKILL_ROOT / "scripts" / "generate_notices.py")])

        audit_path = SKILL_ROOT / "references" / "audit-report.json"
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        summary = audit["summary"]
        print(
            "Validated "
            f"{summary['installed_skills']} specialists; "
            f"{summary['sources_with_unknown_license']} source licenses remain unknown and "
            f"{summary['sources_with_declarations_only']} are declaration-only for redistribution.",
            flush=True,
        )

    if args.sync_only:
        return

    install_command = [
        "npx",
        "--yes",
        args.skills_cli_package,
        "add",
        str(SKILL_ROOT),
        "--skill",
        "cto",
        "-y",
        "--copy",
        "--full-depth",
    ]
    for agent in args.agent:
        install_command.extend(["--agent", agent])
    run(install_command, cwd=target)


if __name__ == "__main__":
    main()
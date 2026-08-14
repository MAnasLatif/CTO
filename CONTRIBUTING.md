# Contributing

Thank you for improving CTO. Contributions should keep the skill concise,
evidence-driven, secure, and useful across different engineering organizations.

## Before You Start

- Open an issue for substantial behavior, catalog, recovery, or licensing changes.
- Keep third-party specialist payloads out of Git. They belong only in the ignored
  `skills/cto/subskills/` directory after local synchronization.
- Preserve source-qualified IDs. Duplicate skill names are intentional.
- Never weaken the explicit approval requirement for network downloads or
  third-party script execution.

## Development

1. Fork the repository and create a focused branch.
2. Make the smallest change that solves the issue.
3. Run `python3 scripts/verify.py`.
4. Describe behavior, security, licensing, and validation impacts in the pull
   request.

The project uses only Python's standard library. Python 3.10 or newer is required.

## Catalog Changes

`skills/cto/references/subskills.json` is the canonical catalog. Catalog pull
requests must explain and review the source-qualified ID, source provenance,
recovery behavior, routing context, and licensing impact. Keep entries sorted by
case-insensitive source-qualified ID and update the summary counts atomically.
The repository verifier rejects duplicates, malformed identities, count drift,
and nondeterministic ordering.

## Pull Requests

By submitting a contribution, you agree that your original contribution is
licensed under this repository's MIT License. Do not submit content you do not
have permission to contribute.
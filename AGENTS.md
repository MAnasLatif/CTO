# Contributor Instructions

- The publishable skill lives in `skills/cto/`; `.agents/` is local tooling only.
- Never commit `skills/cto/subskills/`, generated sync/audit reports, credentials,
  or local skill locks.
- Preserve source-qualified specialist IDs and deterministic manifest ordering.
- Do not execute synchronized third-party scripts during maintenance or CI.
- Keep `skills/cto/SKILL.md` focused on routing and CTO decision quality; detailed
  catalogs and recovery data belong in `references/`.
- Run `python3 scripts/verify.py` before proposing a change.
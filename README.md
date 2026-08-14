# CTO

[![CI](https://github.com/MAnasLatif/CTO/actions/workflows/ci.yml/badge.svg)](https://github.com/MAnasLatif/CTO/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An evidence-driven CTO skill for architecture, engineering, security, AI,
product, delivery, people, operations, finance, risk, metrics, and executive
communication.

The core skill turns business intent into decision-ready technical guidance. It
can route work to a catalog of 193 source-qualified specialist skills without
loading the entire catalog into context.

## Install

### Full Specialist Pack

Requirements: Python 3.10+, Node.js with `npx`, Git, and network access.

```bash
git clone https://github.com/MAnasLatif/CTO.git
cd CTO
python3 scripts/install.py \
  --agent github-copilot \
  --acknowledge-third-party-sources
```

The installer downloads specialists directly from their upstream repositories,
validates the resulting bundle, and copies the complete skill to the selected
agent. Repeat `--agent` to install for more than one supported agent.

### Wrapper Only

Install the MIT-licensed CTO decision framework without downloading specialist
payloads:

```bash
npx skills add https://github.com/MAnasLatif/CTO --skill cto
```

The wrapper can still answer CTO requests, but specialist instruction files are
unavailable until synchronization.

## How It Works

1. Frame the business outcome, constraints, urgency, reversibility, and cost of
   being wrong.
2. Select one primary specialist and up to four supporting specialists.
3. Ground the decision in repository, production, product, or authoritative
   external evidence.
4. Resolve trade-offs across security, reliability, delivery, cost, people, and
   lock-in.
5. Return a recommendation with owners, validation criteria, and review triggers.

Duplicate skill names remain source-qualified, so no provider silently replaces
another. Third-party scripts are never executed during synchronization.

## Repository Layout

```text
.
├── skills/cto/             # Publishable Agent Skill
│   ├── SKILL.md            # CTO orchestration instructions
│   ├── references/         # Catalog, capability map, recovery pins
│   └── scripts/            # Selection, sync, audit, notices
├── scripts/                # Repository install and verification tools
└── THIRD_PARTY_SOURCES.md  # Dependency and licensing boundary
```

Locally synchronized payloads and generated audit reports are ignored by Git.
This keeps the public repository open-source without relicensing third-party
material.

## Development

Run the repository checks before opening a pull request:

```bash
python3 scripts/verify.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution rules and
[SECURITY.md](SECURITY.md) for vulnerability reporting.

## Licensing

Original project code and documentation are licensed under the [MIT License](LICENSE).
Specialist skills are separate upstream works under their own terms and are not
included in the public repository. See [THIRD_PARTY_SOURCES.md](THIRD_PARTY_SOURCES.md).
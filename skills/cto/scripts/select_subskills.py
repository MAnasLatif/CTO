#!/usr/bin/env python3
"""Rank bundled CTO sub-skills for a natural-language request."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = SKILL_ROOT / "references" / "subskills.json"
STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "build", "can", "could",
    "create", "for", "from", "have", "help", "how", "into", "need", "our",
    "please", "should", "that", "the", "their", "this", "use", "using", "want",
    "what", "when", "where", "which", "with", "would", "you", "your",
}

# Triggers map user vocabulary to preferred specialist names. Text matching still
# ranks every catalog entry, so this map is a bias rather than a closed router.
ROUTES = (
    ({"architecture", "architect", "design", "scalability", "system"},
     {"architecture-designer", "architecture-decision", "cto-advisor", "backend-architect"}),
    ({"api", "graphql", "grpc", "openapi", "rest"},
     {"api-design-principles", "api-and-interface-design", "openapi-spec-generation"}),
    ({"database", "schema", "postgres", "mysql", "mongodb", "sqlite", "prisma"},
     {"database-architect", "database-schema-design", "prisma-database-setup"}),
    ({"security", "threat", "owasp", "vulnerability", "auth", "authorization"},
     {"security-best-practices", "security-threat-model", "security-review", "auth-implementation-patterns"}),
    ({"cloud", "aws", "azure", "gcp", "cloudflare", "infrastructure"},
     {"multi-cloud-architecture", "cloudflare", "aws-cloud-architecture", "cloud-design-patterns"}),
    ({"docker", "kubernetes", "terraform", "helm", "deployment", "devops", "ci", "cd"},
     {"docker-patterns", "kubernetes-patterns", "terraform-engineer", "github-actions-templates"}),
    ({"incident", "outage", "latency", "sre", "reliability", "slo"},
     {"slo-implementation", "axiom-sre", "devops-incident-responder", "postmortem-writing"}),
    ({"ai", "llm", "rag", "agent", "prompt", "model", "mcp", "embedding"},
     {"ai-product-strategy", "llm-evaluation", "prompt-engineering-patterns", "rag-implementation", "mcp-builder"}),
    ({"product", "customer", "discovery", "requirements", "prd", "roadmap", "retention"},
     {"feature-spec", "product-capability", "opportunity-solution-tree", "roadmap-planning"}),
    ({"hire", "hiring", "team", "culture", "organization", "manager", "onboarding"},
     {"cto-advisor", "team-composition-analysis", "engineering-culture", "organizational-design"}),
    ({"delivery", "deadline", "estimate", "scope", "ship", "project", "planning"},
     {"planning-under-uncertainty", "managing-timelines", "scoping-cutting", "shipping-products"}),
    ({"market", "pricing", "finance", "cost", "revenue", "runway", "business"},
     {"market-sizing-analysis", "pricing-strategy", "charlie", "startup-financial-modeling"}),
    ({"risk", "compliance", "legal", "audit", "backup", "disaster"},
     {"risk-assessment", "legal-risk-assessment", "database-backup-restore", "security-requirement-extraction"}),
    ({"metric", "kpi", "experiment", "analytics", "dashboard", "data"},
     {"kpi-dashboard-design", "writing-north-star-metrics", "ab-test-setup", "data-storytelling"}),
    ({"communicate", "communication", "executive", "stakeholder", "presentation", "memo"},
     {"internal-comms", "stakeholder-comms", "professional-communication", "managing-up"}),
    ({"documentation", "docs", "adr", "runbook", "changelog", "postmortem"},
     {"technical-writing", "architecture-decision-records", "make-documentation", "postmortem-writing"}),
)


def tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2 and token not in STOP_WORDS
    }


def source_key(entry: dict) -> str:
    return f"{entry['owner']}--{entry['repository']}"


def read_frontmatter_description(skill_file: Path) -> str:
    if not skill_file.exists():
        return ""
    try:
        content = skill_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if not content.startswith("---"):
        return ""
    end = content.find("\n---", 3)
    if end == -1:
        return ""
    frontmatter = content[3:end]
    match = re.search(r"(?m)^description:\s*(.*)$", frontmatter)
    if not match:
        return ""
    value = match.group(1).strip().strip("'\"")
    if value not in {"|", ">", "|-", ">-"}:
        return value
    continuation = frontmatter[match.end():].splitlines()
    return " ".join(line.strip() for line in continuation if line.startswith(" "))


def rank(query: str, manifest: dict, include_missing: bool) -> list[dict]:
    query_tokens = tokens(query)
    query_lower = query.lower()
    routed_names: set[str] = set()
    route_reasons: dict[str, set[str]] = {}
    for triggers, preferred in ROUTES:
        matched = triggers & query_tokens
        if matched:
            routed_names.update(preferred)
            for name in preferred:
                route_reasons.setdefault(name, set()).update(matched)

    ranked: list[dict] = []
    for entry in manifest["skills"]:
        relative_dir = Path("subskills") / source_key(entry) / entry["skill"]
        skill_file = SKILL_ROOT / relative_dir / "SKILL.md"
        installed = skill_file.exists()
        if not installed and not include_missing:
            continue

        description = read_frontmatter_description(skill_file)
        context = " ".join(entry.get("contexts", []))
        searchable = f"{entry['skill']} {context} {description}".lower()
        searchable_tokens = tokens(searchable)
        matched_tokens = sorted(query_tokens & searchable_tokens)
        score = len(matched_tokens) * 4
        if entry["skill"].lower() in query_lower:
            score += 20
        if entry["skill"] in routed_names:
            score += 12
        if entry["skill"] == "cto-advisor" and len(query_tokens) <= 5:
            score += 2
        score += min(entry.get("occurrences", 1) - 1, 3)
        if score == 0:
            continue

        reasons = [f"matched: {', '.join(matched_tokens)}"] if matched_tokens else []
        routed = sorted(route_reasons.get(entry["skill"], set()))
        if routed:
            reasons.append(f"route: {', '.join(routed)}")
        ranked.append(
            {
                "id": entry["id"],
                "skill": entry["skill"],
                "score": score,
                "installed": installed,
                "skill_file": str(relative_dir / "SKILL.md"),
                "reason": "; ".join(reasons) or "catalog relevance",
                "description": description,
            }
        )

    return sorted(ranked, key=lambda item: (-item["score"], item["id"].lower()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="The CTO request to route")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--include-missing", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    results = rank(args.query, manifest, args.include_missing)[: max(args.limit, 1)]
    if args.as_json:
        print(json.dumps(results, indent=2, ensure_ascii=True))
        return
    for result in results:
        marker = "ready" if result["installed"] else "missing"
        print(f"{result['score']:>3}  {marker:<7}  {result['id']}")
        print(f"     {result['reason']} | {result['skill_file']}")


if __name__ == "__main__":
    main()

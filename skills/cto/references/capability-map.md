# CTO Capability Map

Use this map to bias specialist selection, not to bypass
`scripts/select_subskills.py`. The complete inventory and source-qualified IDs
live in `subskills.json`.

| Decision area | Preferred primary skills | Typical supporting skills |
|---|---|---|
| CTO strategy and build-versus-buy | `cto-advisor`, `architecture-decision` | `evaluating-new-technology`, `managing-tech-debt`, `risk-assessment` |
| System and backend architecture | `architecture-designer`, `backend-architect` | `architecture-decision-records`, `032-architecture-adr-non-functional-requirements` |
| APIs and interfaces | `api-design-principles`, `api-and-interface-design` | `openapi-spec-generation`, `auth-implementation-patterns` |
| Data architecture | `database-architect`, `database-schema-design` | `prisma-database-setup`, `redis-development`, `data-quality-frameworks` |
| Distributed and event-driven systems | `microservices-patterns`, `ddd-microservices` | `event-driven`, `slo-implementation`, `monitoring-expert` |
| Cloud and platform selection | `multi-cloud-architecture`, `cloud-design-patterns` | provider-specific skills, `cost-optimization`, `terraform-engineer` |
| Delivery, CI/CD, and infrastructure | `ci-cd-and-automation`, `github-actions-templates` | `docker-patterns`, `kubernetes-patterns`, `helm-chart-scaffolding`, `gh-fix-ci` |
| Security and privacy | `security-best-practices`, `security-threat-model` | `security-review`, `stride-analysis-patterns`, `secrets-management`, `security-requirement-extraction` |
| Reliability and incidents | `slo-implementation`, `axiom-sre` | `devops-incident-responder`, `monitoring-expert`, `postmortem-writing`, `database-backup-restore` |
| AI product and engineering | `ai-product-strategy`, `ai-sdk` | `llm-evaluation`, `rag-implementation`, `prompt-engineering-patterns`, `agentic-top-10` |
| Agents, MCP, and memory | `mcp-builder`, `langchain-architecture` | `mcp-server-patterns`, `agent-memory-systems`, `memory-systems`, `team-composition-patterns` |
| Discovery and product requirements | `conducting-user-interviews`, `feature-spec` | `jobs-to-be-done`, `user-research-synthesis`, `product-capability`, `opportunity-solution-tree` |
| Roadmaps and delivery planning | `roadmap-planning`, `planning-under-uncertainty` | `prioritizing-roadmap`, `task-estimation`, `scoping-cutting`, `shipping-products` |
| Engineering organization and hiring | `cto-advisor`, `team-composition-analysis` | `conducting-interviews`, `evaluating-candidates`, `engineering-culture`, `organizational-design` |
| Leadership and communication | `internal-comms`, `stakeholder-comms` | `managing-up`, `cross-functional-collaboration`, `having-difficult-conversations` |
| Market, pricing, and unit economics | `market-sizing-analysis`, `pricing-strategy` | `competitive-analysis`, `charlie`, `startup-financial-modeling`, `cost-optimization` |
| Risk and compliance | `risk-assessment`, `conducting-cyber-risk-assessment-with-nist-800-30` | `legal-risk-assessment`, `security-compliance-compliance-check`, `skill-security-auditor` |
| Metrics and experimentation | `kpi-dashboard-design`, `writing-north-star-metrics` | `startup-metrics-framework`, `ab-test-setup`, `data-storytelling`, `ai-evals` |
| Technical documentation | `technical-writing`, `architecture-decision-records` | `make-documentation`, `openapi-spec-generation`, `knowledge-management`, `release-notes` |

## Name Collisions

Two names intentionally retain multiple providers. Always use their full IDs:

- `hieutrtr/ai1-skills#project-planner` for implementation-oriented planning.
- `shubhamsaboo/awesome-llm-apps#project-planner` for broader delivery risk and milestones.
- `akillness/oh-my-skills#technical-writing` for architecture and operational writing.
- `supercent-io/skills-template#technical-writing` for broad project and user documentation.

## Selection Discipline

Use one primary specialist to own the method. Add supporting skills only when
they contribute a distinct lens, such as security, economics, reliability,
delivery, or communication. More specialists do not automatically produce a
better decision; unresolved contradictions must be made explicit.

# AGENTS.md

Working agreement for every agent in this repository, vendor-neutral.

## What this repository is

Portfolio project for a Senior Data Engineer: hotel booking across AWS regions with zero double
bookings under concurrent cross-region writes, plus a Databricks lakehouse for occupancy and revenue
analytics. `TASK.md` is the source brief and wins over any
summary here.

Two halves, joined by a change stream:

- **Transactional.** API Gateway + Lambda in two regions over DynamoDB global tables with
  multi-region strong consistency (two active regions plus a witness). Aurora DSQL, the brief's
  first choice, could not be created on the account (ADR 2). Double-booking defence: one
  conditional write per room-night with retry (backoff + jitter), idempotency keys, a hold with TTL
  (`pending` -> `confirmed` / `expired`) driven as a saga in Step Functions with a simulated
  payment.
- **Analytical.** DynamoDB Streams -> Kinesis -> Firehose -> S3 -> Databricks Auto Loader -> Lakeflow
  Declarative Pipelines (medallion, AUTO CDC, expectations) -> Unity Catalog -> Databricks SQL
  dashboards. Exactly-once into Delta is `MERGE` on `event_id`. Lakeflow Jobs orchestrate the
  warehouse.

The proof is a load test: k6 on EC2 spot in three regions sends 1000 concurrent attempts for one
room-night; exactly one succeeds, and an invariant check run afterwards confirms it.

## Contract with the operator

- Session lifecycle is `make up` -> `make demo` -> `make down`. Data is synthetic only; volume is a
  parameter. CI runs the same Make targets a contributor runs.
- Persistent resources are only those free while idle: an empty Databricks workspace, Terraform
  state buckets, registry images. Everything else is created by `make up` and destroyed by
  `make down`.
- A budget alert at $12 and a timed auto-destroy exist before any paid resource is created.
- Target cost is $3-7 per session, mostly Databricks serverless. The workspace is a trial or paid
  workspace on AWS; Free Edition cannot attach to the AWS account.
- IaC is Terraform + Terragrunt (multi-region), CI/CD is GitHub Actions with OIDC (no long-lived
  AWS keys), Databricks code ships as Asset Bundles.

## Problems the project must show worked through, not just tooled

Cross-region concurrent writes; ordering of events from different regions and exactly-once in Delta;
time zones and currencies; data residency for PII. Each one that forces a hard-to-reverse choice
gets an ADR. The README needs an architecture diagram, 3-5 ADRs, a per-run cost report and a
3-minute demo video: the reader is a recruiter who will not run anything.

## How work proceeds

The approval chain is `intent.md` -> `spec.md` -> `plan.md`, each approved by the owner before the
next starts. A diff is compared against the committed `plan.md`; if implementation finds a fact in
the plan false or touches a file outside the approved set, stop and return the plan for approval.

Rule sets live in `.agents/skills/` (`.claude/skills` is a symlink to it; never a second copy).
Each governs a different unit of work:

| Rule set | Use it for |
|---|---|
| `grilling` | interrogating a plan before any of the others start |
| `domain-modeling` | settling terms in `GLOSSARY.md` and hard-to-reverse decisions as ADRs |
| `simplicity-ladder` | one change, before it is written |
| `boundary-dispatch-matrix` | a change that moves execution across a process, queue or service boundary (Lambda, Kinesis, Step Functions, Firehose all qualify) |
| `cherny-workflow` | one session: plan first, checkable items, verify before done |
| `diagnosing-bugs` | a hard bug: red-capable loop before a hypothesis |
| `execution-state` | a long run that is outgrowing its context |
| `agentic-factory` | how many loops land on trunk, and with what evidence |
| `autoresearch` | one measured experiment and its ledger |
| `earned-length` | any comment, response or report: keep only what earns its length |

Source of the method: `ai-factory-kit/` (read `01-method.md` and `10-repo-standard.md` when a
question is about the process rather than the product).

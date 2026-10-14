# AWS + Databricks: hotel booking across 3 regions
A portfolio pet project for a Senior Data Engineer

**Business problem:** zero double bookings under concurrent requests from different regions, plus occupancy and revenue analytics and a semantic hotel search. Hotels only: a "room × night" inventory is simpler than airline seats, while the locking problem is the same. The solution should follow what the world's leading sites such as Airbnb and Booking use. The main goal, though, is to show Data Engineer experience through ETL processes and data presentation in Databricks.

**Transactional part:**

- **Backend:** Lambda + API Gateway in two regions.
- **Database:** Aurora DSQL multi-region (two active regions plus a witness, three in total).
- **Double-booking protection:** optimistic concurrency with retry (backoff + jitter), idempotency keys, a hold with TTL (pending → confirmed/expired, a saga with a "payment").
- **Proof:** k6 on EC2 spot from three regions sends 1000 concurrent attempts for one room; exactly one succeeds, and an invariant query run after the test confirms it.
- **Alternative to DSQL:** DynamoDB Global Tables with strong consistency and conditional writes.

**Analytical part:** outbox table → Kinesis → Firehose → S3 → Databricks Auto Loader → Lakeflow Declarative Pipelines (medallion, AUTO CDC, expectations) → Unity Catalog → Databricks SQL dashboards.

- **Metrics:** occupancy, ADR, RevPAR, booking pace, lead time, cancellation rate, conflict rate by region.
- **Vector part:** Bedrock Knowledge Base on S3 Vectors with descriptions and reviews. A query like "quiet seaside hotel with parking" plus a filter by real availability from DSQL. OpenSearch Serverless does not fit: its minimum charge is high.
- **Orchestration:** Lakeflow Jobs for the warehouse, Step Functions for the saga.
- **IaC and CI/CD:** Terraform + Terragrunt (multi-region), GitHub Actions with OIDC, Databricks Asset Bundles.

**Problems to show worked through:**

- concurrent writes across regions;
- ordering of events from different regions, exactly-once in Delta (MERGE on event\_id);
- time zones and currencies;
- data residency for PII.

**Cost:** $3–7 per session, almost all of it Databricks serverless. A trial or paid workspace on AWS is required: Free Edition cannot be attached to your own AWS account.

## What this project covers

|  | AWS + Databricks |
| --- | --- |
| Workload type | OLTP + lakehouse |
| Engine | Databricks, Aurora DSQL |
| Broker / CDC | Kinesis, outbox |
| Format | Delta + Unity Catalog |
| Transformations | Declarative Pipelines |
| Orchestration | Lakeflow Jobs, Step Functions |
| Data quality | Expectations |
| Specialised DB | vector (Bedrock) |
| BI | Databricks SQL |
| IaC / CI | Terraform as multi-region via Terragrunt, GitHub Actions |

## Rules

- **Lifecycle:** `make up` → `make demo` (generator and load) → `make down`. Data is synthetic only; volume is a parameter.
- **Persistent resources:** only those that are free while idle: an empty Databricks workspace, state buckets, registry images. Otherwise 20 minutes of a 30-minute session go to provisioning.
- **Safety net against forgotten resources:** a budget alert at $12 and a timed auto-destroy.
- **Packaging:** a recruiter will not run anything, so the README needs an architecture diagram, 3–5 ADRs ("why this and not that"), a per-run cost report and a 3-minute demo video. Senior level is shown by the ADRs and the problems worked through, not by a list of tools.

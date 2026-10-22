# Cloud run: the owner's steps

The steps only the account owner can take, in order. Everything else runs in the `cloud-session`
workflow. The plan is `plan.md`; the budget alert at $12 and the reaper are the safety nets.

## Once, before the first run

1. **Cost allocation tag.** Billing and Cost Management, Cost allocation tags: activate `project`.
   Activation takes up to 24 hours, so do it at least a day before the run.
2. **Sign in locally**, for the checks below: `aws sso login --profile booking-admin`.
3. **Default VPCs.** Each k6 instance runs in its region's default VPC with a public IP. Check that
   all three regions have one:

   ```sh
   for r in us-east-1 us-east-2 us-west-2; do
     aws --profile booking-admin --region $r ec2 describe-vpcs \
       --filters Name=is-default,Values=true --query 'Vpcs[].VpcId' --output text
   done
   ```

   A region that prints nothing needs `aws ec2 create-default-vpc --region <r>`.
4. **Spot quota.** Each region runs one c7g.large (2 vCPU). The quota "All Standard (A, C, D, H, I,
   M, R, T, Z) Spot Instance Requests" must be at least 2 in each region:

   ```sh
   for r in us-east-1 us-east-2 us-west-2; do
     aws --profile booking-admin --region $r service-quotas get-service-quota \
       --service-code ec2 --quota-code L-34B43A08 --query 'Quota.Value' --output text
   done
   ```

## Run 1, AWS only

1. Actions, `cloud-session`, Run workflow, scale `small`. Approve the `demo-prod` deployment.
2. The run takes about 40 minutes:
   - `make up`, about 15 minutes, most of it the MRSC tables and the KB ingestion;
   - `make demo`, about 15 minutes, most of it waiting for the k6 instances;
   - `make down`.
3. Download the `cloud-session-<run id>` artifact. `demo.json` says which steps passed; each step
   has its own JSON beside it.
4. Once run 1 is green, set the repository variable `REAPER_ENABLED=true`. From then on a session
   that outlives its two hours is destroyed within 30 minutes.
5. The next day, run `make cost-report DATE=<run date>` locally. It writes
   `artifacts/cost-<date>.json`. Each Cost Explorer call costs $0.01, and the report makes two.

## Search on an account without Bedrock model access

On 2026-10-21 run 1 stopped at the knowledge base ingestion: every Bedrock model on the account
answers `Operation not allowed`, and `get-foundation-model-availability` reports
`authorizationStatus: NOT_AUTHORIZED`. The block is on the account, not in the knowledge base role:
the admin role gets the same answer.

Until it is lifted, run `cloud-session` with `search` unticked. `make up SEARCH=off` still applies
the search unit (the knowledge base, the S3 Vectors index, the corpus bucket), but skips the corpus
ingestion; `make demo SEARCH=off` leaves out the `search` step. Everything else runs as usual.

To bring search up once access is granted:

1. Check that the embedding model answers:

   ```sh
   aws --profile booking-admin --region us-east-1 bedrock get-foundation-model-availability \
     --model-id amazon.titan-embed-text-v2:0 --query authorizationStatus --output text
   ```

   It must print `AUTHORIZED`.
2. Run `cloud-session` with `search` ticked (the default). `make up` ingests the corpus and
   `make demo` runs the `search` step: every hotel `/search` returns has a free room, and a hotel
   booked out for the stay is left out.

Locally, the same is `make up` then `make demo`, with `SEARCH=on` or no `SEARCH` at all.

## If a run is interrupted

`make down` runs with `if: always()`. If the runner itself died, run `make down` locally with the
same profile, or wait for the reaper. `make down` keeps the landing bucket and the MRSC table, which
cost nothing while empty.

`make destroy-persistent` removes what `make down` keeps: the landing bucket, the MRSC table and,
with `DATABRICKS_HOST` set, the Unity Catalog objects and the bundle. CI never runs it.

## Run 2, with Databricks

The trial lasts 14 days from signup, so sign up only once run 1 is green and every slice is merged
(plan D9).

1. **Trial.** At databricks.com/try-databricks, sign up with express setup on AWS, region
   us-east-1. Note the workspace URL, `https://dbc-<id>.cloud.databricks.com`.
2. **Service principal.** In the workspace: Settings, Identity and access, Service principals, Add.
   Name it `booking-ci`. Then:
   - add it to the `admins` group, so it can create the storage credential, the external location
     and the catalog;
   - on its Secrets tab, generate an OAuth secret, and copy the client ID and the secret.
3. **GitHub.** Settings, Environments, `demo-prod`:
   - variable `DATABRICKS_HOST`: the workspace URL;
   - variable `DATABRICKS_CLIENT_ID`: the client ID;
   - secret `DATABRICKS_CLIENT_SECRET`: the secret.
4. **Probe**, locally, before the run: `make databricks-probe` with the three values exported in
   the shell. It applies only the persistent `landing` and `databricks_uc` units, then runs
   `databricks bundle validate` against the workspace. It checks that the trial accepts a storage
   credential on our bucket (plan D10). Nothing it creates costs anything while idle. If the
   external location is refused, stop: the volume fallback (plan D10) is written first.
5. **Run 2.** Actions, `cloud-session`, scale `small`. With `DATABRICKS_HOST` set, `make up` also
   applies `databricks_uc` and deploys the bundle, and `make demo` adds the `lakehouse` step: it
   waits for Firehose, runs `booking-refresh` and records gold by region, conflict rates and KPIs.
6. **Cost report**, the next day, with the three values exported: `make cost-report DATE=<date>`
   adds the Databricks share from `system.billing.usage`. If the system tables are off, read the
   day's usage from the account console instead.

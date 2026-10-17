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
   - `make up`, about 15 minutes, most of it DSQL and the KB ingestion;
   - `make demo`, about 15 minutes, most of it waiting for the k6 instances;
   - `make down`.
3. Download the `cloud-session-<run id>` artifact. `demo.json` says which steps passed; each step
   has its own JSON beside it.
4. Once run 1 is green, set the repository variable `REAPER_ENABLED=true`. From then on a session
   that outlives its two hours is destroyed within 30 minutes.
5. The next day, run `make cost-report DATE=<run date>` locally. It writes
   `artifacts/cost-<date>.json`. Each Cost Explorer call costs $0.01, and the report makes two.

## If a run is interrupted

`make down` runs with `if: always()`. If the runner itself died, run `make down` locally with the
same profile, or wait for the reaper. `make down` keeps the landing bucket and the MRSC table, which
cost nothing while empty.

## Run 2, with Databricks

Added in slice C3: the trial signup, the service principal and the GitHub secrets.

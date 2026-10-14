# One-time account bootstrap

Done once per AWS account, by its owner. It creates only resources that are free while idle:

| Resource | Purpose |
|---|---|
| S3 bucket `booking-tfstate-<account-id>` | Terraform state for `infra/live/demo-prod` (S3 native lockfile) |
| GitHub OIDC provider | GitHub Actions authenticates without long-lived keys |
| Role `booking-gha-plan` | `ReadOnlyAccess`; assumable from pull requests and `main` of this repository |
| Role `booking-gha-deploy` | `PowerUserAccess` plus IAM limited to `booking-*`; assumable only from the `demo-prod` and `demo-reaper` environments |
| Budget `booking-monthly` | $12 per month; email at 50% and 100% actual, and at 100% forecast |

Host prerequisites: Docker Desktop, GNU Make, AWS CLI v2, `gh` logged in. Run commands in Git Bash
from the repository root.

## 1. Secure the root user

1. Sign in to the [AWS console](https://console.aws.amazon.com/) as the root user.
2. Account menu -> **Security credentials** -> **Assign MFA device**. Use an authenticator app or a
   passkey.
3. Account menu -> **Account** -> **IAM user and role access to Billing information** -> **Edit** ->
   tick **Activate IAM Access** -> **Update**. Without it the SSO user cannot manage the budget.

After this step the root user is not used again.

## 2. Create an organization

IAM Identity Center can grant access to an AWS account only from an organization instance, so the
account becomes the management account of a one-account organization. Organizations is free.

1. Console -> **AWS Organizations** -> **Create an organization**.
2. Confirm the verification email AWS sends to the root address.

## 3. Enable IAM Identity Center and create your user

1. Switch the console region to **US East (N. Virginia) us-east-1**.
2. Console -> **IAM Identity Center** -> **Enable**. Choose the organization instance.
3. **Users** -> **Add user**. Username, email, first and last name -> **Next** -> **Add user**.
4. Open the invitation email, accept it, set a password and register an MFA device.
5. **Permission sets** -> **Create permission set** -> **Predefined permission set** ->
   `AdministratorAccess` -> session duration **4 hours** -> **Create**.
6. **AWS accounts** -> tick your account -> **Assign users or groups** -> your user ->
   `AdministratorAccess` -> **Submit**.
7. **Settings** -> copy the **AWS access portal URL** (`https://d-xxxxxxxxxx.awsapps.com/start`).

## 4. Log in from the CLI

```bash
aws configure sso
#   SSO session name:        booking
#   SSO start URL:           <the access portal URL from 3.7>
#   SSO region:              us-east-1
#   SSO registration scopes: <Enter>
#   (a browser opens: approve)
#   account and role:        your account, AdministratorAccess
#   Default client Region:   us-east-1
#   CLI default output:      json
#   Profile name:            booking-admin

aws sso login --profile booking-admin
aws sts get-caller-identity --profile booking-admin
```

The last command prints your account ID and an `AWSReservedSSO_AdministratorAccess_...` ARN.
`aws sso login` is repeated whenever the session expires (4 hours).

## 5. Apply the bootstrap

The dev container reads `~/.aws` from the host, so the SSO login above works inside it.

```bash
export AWS_PROFILE=booking-admin
export TF_VAR_budget_email='<your email for budget alerts>'
docker compose run --rm --no-deps dev sh -c 'cd infra/bootstrap && terraform init && terraform apply'
```

Read the plan before typing `yes`: it must say `Plan: 12 to add, 0 to change, 0 to destroy.`

The state of this step stays local in `infra/bootstrap/terraform.tfstate` (gitignored). Keep a copy
outside the repository: it is needed to change or destroy these resources later.

## 6. Connect GitHub

```bash
out() { docker compose run --rm --no-deps -T dev terraform -chdir=infra/bootstrap output -raw "$1"; }
gh variable set AWS_PLAN_ROLE_ARN --body "$(out plan_role_arn)"
gh variable set AWS_DEPLOY_ROLE_ARN --body "$(out deploy_role_arn)"

REPO=AlexBormotov/databricks-multi-region-booking-aws
ME=$(gh api user --jq .id)
# demo-prod: every cloud-session run waits for your approval.
gh api -X PUT "repos/$REPO/environments/demo-prod" --input - <<EOF
{"reviewers": [{"type": "User", "id": $ME}]}
EOF
# demo-reaper: no reviewer, runs only from main.
gh api -X PUT "repos/$REPO/environments/demo-reaper" --input - <<'EOF'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
EOF
gh api -X POST "repos/$REPO/environments/demo-reaper/deployment-branch-policies" -f name=main
```

## 7. Check

```bash
make plan
```

Every component under `infra/live/demo-prod` plans to `No changes.` A pull request now gets the same
plan as a comment from the `plan` job.

## Undo

```bash
docker compose run --rm --no-deps dev sh -c 'cd infra/bootstrap && terraform destroy'
```

The state bucket must be empty first. The organization and IAM Identity Center are removed in the
console.

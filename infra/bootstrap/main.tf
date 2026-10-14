# One-time account setup, applied by the owner with local state (docs/bootstrap.md).
# Everything here is free while idle.

terraform {
  required_version = ">= 1.16"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.68"
    }
  }
}

provider "aws" {
  region = "us-east-1"
  default_tags {
    tags = { project = "booking", managed_by = "terraform-bootstrap" }
  }
}

variable "github_repo" {
  type    = string
  default = "AlexBormotov/databricks-multi-region-booking-aws"
}

variable "budget_email" {
  type        = string
  description = "Receives the budget alerts. Pass as TF_VAR_budget_email; never commit it."
}

variable "budget_usd" {
  type    = number
  default = 12
}

data "aws_caller_identity" "this" {}

locals {
  account_id = data.aws_caller_identity.this.account_id
}

# --- Terraform state for the demo-prod tree (S3 native lockfile, no DynamoDB table) ---

resource "aws_s3_bucket" "state" {
  bucket = "booking-tfstate-${local.account_id}"
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- GitHub Actions OIDC ---

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "trust" {
  for_each = {
    # Pull requests and main may plan; fork PRs never receive an OIDC token.
    plan = ["repo:${var.github_repo}:pull_request", "repo:${var.github_repo}:ref:refs/heads/main"]
    # Only jobs bound to these environments may deploy; demo-prod has a required reviewer.
    deploy = ["repo:${var.github_repo}:environment:demo-prod", "repo:${var.github_repo}:environment:demo-reaper"]
  }

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = each.value
    }
  }
}

resource "aws_iam_role" "plan" {
  name                 = "booking-gha-plan"
  assume_role_policy   = data.aws_iam_policy_document.trust["plan"].json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "plan_read_only" {
  role       = aws_iam_role.plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# `make plan` also validates the saga's state machine definition, a free API call outside ReadOnlyAccess.
resource "aws_iam_role_policy" "plan_validate_asl" {
  role = aws_iam_role.plan.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "states:ValidateStateMachineDefinition"
      Resource = "*"
    }]
  })
}

resource "aws_iam_role" "deploy" {
  name                 = "booking-gha-deploy"
  assume_role_policy   = data.aws_iam_policy_document.trust["deploy"].json
  max_session_duration = 7200
}

# PowerUserAccess covers every service the stack uses but not IAM. IAM writes are limited to
# booking-* roles and policies, and every role the deploy role creates or changes must carry the
# PowerUserAccess permissions boundary. A role it creates can therefore never hold more than
# PowerUserAccess, even with AdministratorAccess attached. The two bootstrap roles are off-limits.
resource "aws_iam_role_policy_attachment" "deploy_power_user" {
  role       = aws_iam_role.deploy.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

locals {
  boundary_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
  project_iam = [
    "arn:aws:iam::${local.account_id}:role/booking-*",
    "arn:aws:iam::${local.account_id}:policy/booking-*",
    "arn:aws:iam::${local.account_id}:instance-profile/booking-*",
  ]
}

resource "aws_iam_role_policy" "deploy_iam" {
  role = aws_iam_role.deploy.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "GrantOnlyInsideTheBoundary"
        Effect   = "Allow"
        Action   = ["iam:CreateRole", "iam:PutRolePermissionsBoundary", "iam:AttachRolePolicy", "iam:PutRolePolicy"]
        Resource = local.project_iam
        Condition = {
          StringEquals = { "iam:PermissionsBoundary" = local.boundary_arn }
        }
      },
      {
        Sid    = "ManageProjectRolesAndPolicies"
        Effect = "Allow"
        Action = [
          "iam:DeleteRole", "iam:UpdateRole", "iam:UpdateRoleDescription", "iam:UpdateAssumeRolePolicy",
          "iam:DetachRolePolicy", "iam:DeleteRolePolicy", "iam:TagRole", "iam:UntagRole", "iam:PassRole",
          "iam:CreatePolicy", "iam:DeletePolicy", "iam:CreatePolicyVersion", "iam:DeletePolicyVersion",
          "iam:SetDefaultPolicyVersion", "iam:TagPolicy", "iam:UntagPolicy",
          "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile", "iam:AddRoleToInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile", "iam:TagInstanceProfile", "iam:UntagInstanceProfile",
        ]
        Resource = local.project_iam
      },
      {
        Sid      = "ReadIam"
        Effect   = "Allow"
        Action   = ["iam:Get*", "iam:List*"]
        Resource = "*"
      },
      {
        Sid      = "KeepTheBoundary"
        Effect   = "Deny"
        Action   = "iam:DeleteRolePermissionsBoundary"
        Resource = "*"
      },
      {
        Sid      = "LeaveBootstrapRolesAlone"
        Effect   = "Deny"
        Action   = "iam:*"
        Resource = [aws_iam_role.plan.arn, "arn:aws:iam::${local.account_id}:role/booking-gha-deploy"]
      },
    ]
  })
}

# --- Budget ---

resource "aws_budgets_budget" "monthly" {
  name         = "booking-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_email]
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}

output "state_bucket" {
  value = aws_s3_bucket.state.id
}

output "plan_role_arn" {
  value = aws_iam_role.plan.arn
}

output "deploy_role_arn" {
  value = aws_iam_role.deploy.arn
}

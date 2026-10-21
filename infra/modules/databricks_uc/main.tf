# Unity Catalog over the landing bucket (spec 4, plan D10): a storage credential on an IAM role, an
# external location, the `booking` catalog with its three schemas, and the SQL warehouse for the
# job's checks and the dashboard. Persistent (plan D11): none of it costs anything while idle, and
# a stopped serverless warehouse bills nothing.

data "aws_caller_identity" "this" {}

locals {
  role_name = "booking-uc-landing"
}

# The credential comes first, because the role's trust policy needs its external ID. It names the
# role by ARN, which breaks the cycle.
resource "databricks_storage_credential" "landing" {
  name = "booking-landing"
  aws_iam_role {
    role_arn = "arn:aws:iam::${data.aws_caller_identity.this.account_id}:role/${local.role_name}"
  }
}

# Trusts the Databricks Unity Catalog master role with the credential's external ID, and the role
# itself, as Unity Catalog requires.
data "databricks_aws_unity_catalog_assume_role_policy" "landing" {
  aws_account_id = data.aws_caller_identity.this.account_id
  role_name      = local.role_name
  external_id    = databricks_storage_credential.landing.aws_iam_role[0].external_id
}

data "databricks_aws_unity_catalog_policy" "landing" {
  aws_account_id = data.aws_caller_identity.this.account_id
  bucket_name    = var.landing_bucket
  role_name      = local.role_name
}

resource "aws_iam_role" "landing" {
  name                 = local.role_name
  assume_role_policy   = data.databricks_aws_unity_catalog_assume_role_policy.landing.json
  permissions_boundary = var.permissions_boundary
}

resource "aws_iam_role_policy" "landing" {
  role   = aws_iam_role.landing.id
  policy = data.databricks_aws_unity_catalog_policy.landing.json
}

# Creating the external location validates access through the role; IAM needs a moment first.
resource "time_sleep" "iam" {
  depends_on      = [aws_iam_role_policy.landing]
  create_duration = "30s"
}

resource "databricks_external_location" "landing" {
  name            = "booking-landing"
  url             = "s3://${var.landing_bucket}"
  credential_name = databricks_storage_credential.landing.id
  read_only       = true
  depends_on      = [time_sleep.iam]
}

# Managed tables live in the workspace's default storage, not in the landing bucket that
# `make down` empties.
resource "databricks_catalog" "booking" {
  name    = "booking"
  comment = "Hotel booking lakehouse."
}

resource "databricks_schema" "layer" {
  for_each     = toset(["bronze", "silver", "gold"])
  catalog_name = databricks_catalog.booking.name
  name         = each.key
}

resource "databricks_sql_endpoint" "demo" {
  name                      = "booking"
  cluster_size              = "2X-Small"
  max_num_clusters          = 1
  auto_stop_mins            = 5
  enable_serverless_compute = true
  warehouse_type            = "PRO"
}

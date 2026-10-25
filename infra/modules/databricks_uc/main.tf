# Unity Catalog over the landing bucket (spec 4, plan D10): a storage credential on an IAM role, an
# external location, the `booking` catalog with its three schemas, and the SQL warehouse for the
# job's checks and the dashboard. The catalog keeps its managed tables in a bucket of its own. Persistent (plan D11): none of it costs anything while idle, and
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

# The express trial's metastore has no storage root, so the catalog needs one. A bucket apart from
# landing, which `make down` empties. force_destroy: `make destroy-persistent` drops the tables too.
resource "aws_s3_bucket" "lakehouse" {
  bucket        = "booking-lakehouse-${data.aws_caller_identity.this.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "lakehouse" {
  bucket                  = aws_s3_bucket.lakehouse.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lakehouse" {
  bucket = aws_s3_bucket.lakehouse.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_iam_role_policy" "lakehouse" {
  role = aws_iam_role.landing.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:GetBucketLocation",
        "s3:ListBucketMultipartUploads", "s3:ListMultipartUploadParts", "s3:AbortMultipartUpload",
      ]
      Resource = [aws_s3_bucket.lakehouse.arn, "${aws_s3_bucket.lakehouse.arn}/*"]
    }]
  })
}

# Creating the external location validates access through the role; IAM needs a moment first.
resource "time_sleep" "iam" {
  depends_on      = [aws_iam_role_policy.landing]
  create_duration = "30s"
  # Waits again when the lakehouse grant is added to a role that already exists.
  triggers = {
    lakehouse = aws_iam_role_policy.lakehouse.id
  }
}

resource "databricks_external_location" "landing" {
  name            = "booking-landing"
  url             = "s3://${var.landing_bucket}"
  credential_name = databricks_storage_credential.landing.id
  read_only       = true
  depends_on      = [time_sleep.iam]
}

resource "databricks_external_location" "lakehouse" {
  name            = "booking-lakehouse"
  url             = "s3://${aws_s3_bucket.lakehouse.bucket}"
  credential_name = databricks_storage_credential.landing.id
  # Dropped managed tables stay registered for 7 days; the bucket goes with force_destroy anyway.
  force_destroy = true
  depends_on    = [time_sleep.iam]
}

resource "databricks_catalog" "booking" {
  name    = "booking"
  comment = "Hotel booking lakehouse."
  # Spelled out with the trailing slash the API adds; the location's url gains it only after apply,
  # which the provider reports as an inconsistent plan.
  storage_root  = "s3://${aws_s3_bucket.lakehouse.bucket}/"
  force_destroy = true # the pipeline's tables are not in Terraform state
  depends_on    = [databricks_external_location.lakehouse]
}

resource "databricks_schema" "layer" {
  for_each      = toset(["bronze", "silver", "gold"])
  catalog_name  = databricks_catalog.booking.name
  name          = each.key
  force_destroy = true
}

resource "databricks_sql_endpoint" "demo" {
  name                      = "booking"
  cluster_size              = "2X-Small"
  max_num_clusters          = 1
  auto_stop_mins            = 5
  enable_serverless_compute = true
  warehouse_type            = "PRO"
}

# The catalog is owned by the CI service principal, so people in the workspace could neither see
# it nor read the dashboard's tables. Read only: the pipeline writes as its owner.
resource "databricks_grants" "booking" {
  catalog = databricks_catalog.booking.name
  grant {
    principal  = "account users"
    privileges = ["BROWSE", "USE_CATALOG", "USE_SCHEMA", "SELECT"]
  }
}

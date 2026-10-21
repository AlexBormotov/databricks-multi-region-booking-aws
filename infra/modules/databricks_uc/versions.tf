terraform {
  required_version = ">= 1.16"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.68"
    }
    # Authenticates from DATABRICKS_HOST, DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET.
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.137"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
  }
}

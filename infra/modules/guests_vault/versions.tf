# Resources arrive in plan.md step 10; until then the component plans to no changes.
terraform {
  required_version = ">= 1.16"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.68"
    }
  }
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  region = read_terragrunt_config(find_in_parent_folders("region.hcl")).locals.region
}

terraform {
  source = "${get_repo_root()}/infra/modules//saga"
}

dependency "dsql" {
  config_path = "${get_repo_root()}/infra/live/demo-prod/us-east-1/dsql"
  mock_outputs = {
    endpoints    = { "us-east-1" = "mock.dsql.us-east-1.on.aws", "us-east-2" = "mock.dsql.us-east-2.on.aws" }
    cluster_arns = { "us-east-1" = "arn:aws:dsql:us-east-1:123456789012:cluster/mock", "us-east-2" = "arn:aws:dsql:us-east-2:123456789012:cluster/mock" }
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "plan"]
}

inputs = {
  dsql_endpoint    = dependency.dsql.outputs.endpoints[local.region]
  dsql_cluster_arn = dependency.dsql.outputs.cluster_arns[local.region]
}

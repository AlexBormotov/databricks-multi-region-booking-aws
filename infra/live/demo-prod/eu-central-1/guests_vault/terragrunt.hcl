include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "${get_repo_root()}/infra/modules//guests_vault"
}

inputs = {
  table_name = "guests-eu"
}

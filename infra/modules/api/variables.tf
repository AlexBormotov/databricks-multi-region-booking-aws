variable "permissions_boundary" {
  type = string
}

variable "package_path" {
  type        = string
  description = "Lambda zip built by make package."
}

variable "dsql_endpoint" {
  type = string
}

variable "dsql_cluster_arn" {
  type = string
}

variable "stream_name" {
  type = string
}

variable "stream_arn" {
  type = string
}

variable "state_machine_arn" {
  type = string
}

variable "guest_vault_arns" {
  type = list(string)
}

variable "knowledge_base_id" {
  type        = string
  description = "Search knowledge base in us-east-1; both regions call it."
}

variable "knowledge_base_arn" {
  type = string
}

variable "hold_ttl_s" {
  type    = number
  default = 900
}

variable "permissions_boundary" {
  type        = string
  description = "Boundary every role carries (docs/bootstrap.md)."
}

variable "landing_bucket_arn" {
  type        = string
  description = "The persistent landing bucket (infra/modules/landing)."
}

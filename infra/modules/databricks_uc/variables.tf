variable "landing_bucket" {
  type        = string
  description = "The landing bucket Unity Catalog reads through the external location."
}

variable "permissions_boundary" {
  type        = string
  description = "Boundary every role carries (docs/bootstrap.md)."
}

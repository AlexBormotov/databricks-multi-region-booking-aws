variable "permissions_boundary" {
  type = string
}

variable "package_path" {
  type        = string
  description = "Lambda zip built by make package."
}

variable "store_tables" {
  type = list(string)
}

variable "hold_ttl_s" {
  type    = number
  default = 900
}

variable "payment_failure_rate" {
  type    = number
  default = 0.1
}

variable "payment_latency_s" {
  type    = number
  default = 2
}

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

variable "store_stream_arn" {
  type        = string
  default     = null
  description = "The bookings stream; set only in us-east-1, the region that has it."
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

variable "hold_ttl_s" {
  type    = number
  default = 900
}

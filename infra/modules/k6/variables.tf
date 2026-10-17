variable "permissions_boundary" {
  type        = string
  description = "Boundary every role carries (docs/bootstrap.md)."
}

variable "start_at_ms" {
  type        = number
  default     = 0
  description = "Epoch milliseconds when every VU fires; 0 creates nothing."
}

variable "run_id" {
  type    = string
  default = "none"
}

variable "api_urls" {
  type = list(string)
}

variable "hotel_id" {
  type    = string
  default = ""
}

variable "room_id" {
  type    = string
  default = ""
}

variable "check_in" {
  type    = string
  default = "2027-03-01"
}

variable "check_out" {
  type    = string
  default = "2027-03-02"
}

variable "attempts" {
  type        = number
  default     = 0
  description = "This instance's share of the attempts."
}

variable "results_bucket" {
  type = string
}

variable "results_bucket_arn" {
  type = string
}

variable "script_path" {
  type = string
}

variable "instance_type" {
  type    = string
  default = "c7g.large"
}

variable "k6_version" {
  type    = string
  default = "2.3.0"
}

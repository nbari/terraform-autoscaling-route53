variable "name" {
  description = "SNS topic name"
  type        = string
  default     = "autoscaling-route53"
}

variable "zone_id" {
  description = "Route53 zone ID"
  type        = string
}

variable "ttl" {
  description = "TTL for the record"
  type        = number
  default     = 60
}

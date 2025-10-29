# DynamoDB Module Variables

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "replica_regions" {
  description = "List of regions for DynamoDB Global Table replicas (excluding primary region)"
  type        = list(string)
  default     = []
}

variable "enable_point_in_time_recovery" {
  description = "Enable point-in-time recovery for tables"
  type        = bool
  default     = true
}

variable "kms_key_arn" {
  description = "KMS key ARN for server-side encryption (optional, uses AWS managed key if not provided)"
  type        = string
  default     = null
}

variable "enable_cloudwatch_alarms" {
  description = "Enable CloudWatch alarms for DynamoDB tables"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

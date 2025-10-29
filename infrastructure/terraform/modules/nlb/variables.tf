# NLB Module Variables

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs for NLB (use public subnets)"
  type        = list(string)
}

variable "internal" {
  description = "Whether NLB is internal (true) or internet-facing (false)"
  type        = bool
  default     = false # Internet-facing for Global Accelerator
}

variable "enable_deletion_protection" {
  description = "Enable deletion protection on NLB"
  type        = bool
  default     = true
}

variable "enable_cross_zone_load_balancing" {
  description = "Enable cross-zone load balancing"
  type        = bool
  default     = true
}

variable "enable_http_listener" {
  description = "Enable HTTP listener on port 8080"
  type        = bool
  default     = true
}

variable "enable_cloudwatch_alarms" {
  description = "Enable CloudWatch alarms for NLB"
  type        = bool
  default     = true
}

variable "max_active_connections" {
  description = "Threshold for active connections alarm"
  type        = number
  default     = 10000
}

variable "max_response_time_seconds" {
  description = "Threshold for target response time alarm (seconds)"
  type        = number
  default     = 5.0
}

variable "enable_privatelink_service" {
  description = "Enable VPC Endpoint Service for PrivateLink (Feature 2B)"
  type        = bool
  default     = false
}

variable "privatelink_acceptance_required" {
  description = "Require manual acceptance for PrivateLink connections"
  type        = bool
  default     = true
}

variable "privatelink_allowed_principals" {
  description = "List of AWS principal ARNs allowed to connect via PrivateLink"
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

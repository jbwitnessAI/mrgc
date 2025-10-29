# Global Accelerator Module Variables

variable "name" {
  description = "Name of the Global Accelerator"
  type        = string
}

variable "enabled" {
  description = "Enable the Global Accelerator"
  type        = bool
  default     = true
}

variable "regions" {
  description = "List of regions to include in Global Accelerator"
  type        = list(string)
  default     = ["us-east-1", "us-east-2", "us-west-2"]
}

variable "endpoint_arns" {
  description = "Map of region -> NLB ARN for endpoint configuration"
  type        = map(string)
}

variable "endpoint_weights" {
  description = "Map of region -> weight (0-255) for traffic distribution"
  type        = map(number)
  default = {
    "us-east-1" = 128
    "us-east-2" = 128
    "us-west-2" = 128
  }
}

variable "traffic_dial_percentages" {
  description = "Map of region -> traffic dial percentage (0-100)"
  type        = map(number)
  default = {
    "us-east-1" = 100
    "us-east-2" = 100
    "us-west-2" = 100
  }
}

variable "client_affinity" {
  description = "Client affinity (NONE or SOURCE_IP)"
  type        = string
  default     = "NONE" # Better load balancing
}

variable "enable_http_listener" {
  description = "Enable HTTP listener on port 8080"
  type        = bool
  default     = true
}

variable "health_check_interval_seconds" {
  description = "Health check interval in seconds"
  type        = number
  default     = 30
}

variable "health_check_protocol" {
  description = "Health check protocol (TCP or HTTP)"
  type        = string
  default     = "TCP"
}

variable "health_check_port" {
  description = "Health check port (defaults to traffic port if not specified)"
  type        = number
  default     = null
}

variable "health_check_path" {
  description = "Health check path (for HTTP health checks)"
  type        = string
  default     = null
}

variable "health_check_threshold_count" {
  description = "Number of consecutive health checks before marking endpoint healthy/unhealthy"
  type        = number
  default     = 3
}

variable "flow_logs_enabled" {
  description = "Enable flow logs for Global Accelerator"
  type        = bool
  default     = true
}

variable "flow_logs_s3_bucket" {
  description = "S3 bucket for flow logs"
  type        = string
  default     = null
}

variable "flow_logs_s3_prefix" {
  description = "S3 prefix for flow logs"
  type        = string
  default     = "global-accelerator-logs/"
}

variable "enable_cloudwatch_alarms" {
  description = "Enable CloudWatch alarms"
  type        = bool
  default     = true
}

variable "max_new_flows_threshold" {
  description = "Threshold for new flows alarm"
  type        = number
  default     = 100000
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

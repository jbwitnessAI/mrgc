# FSx Lustre Module Variables

variable "cluster_name" {
  description = "Name of the GPU cluster"
  type        = string
}

variable "region_code" {
  description = "Short region code (e.g., use1, use2, usw2)"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs for FSx (use FSx subnets)"
  type        = list(string)
}

variable "security_group_ids" {
  description = "List of security group IDs for FSx"
  type        = list(string)
}

variable "storage_capacity_gb" {
  description = "Storage capacity in GB (must be 1200, 2400, or increments of 2400)"
  type        = number
  default     = 1200

  validation {
    condition     = var.storage_capacity_gb == 1200 || var.storage_capacity_gb == 2400 || (var.storage_capacity_gb > 2400 && var.storage_capacity_gb % 2400 == 0)
    error_message = "Storage capacity must be 1200, 2400, or increments of 2400 GB."
  }
}

variable "deployment_type" {
  description = "FSx deployment type (PERSISTENT_1 or PERSISTENT_2)"
  type        = string
  default     = "PERSISTENT_1"

  validation {
    condition     = contains(["PERSISTENT_1", "PERSISTENT_2"], var.deployment_type)
    error_message = "Deployment type must be PERSISTENT_1 or PERSISTENT_2."
  }
}

variable "storage_type" {
  description = "Storage type (SSD or HDD)"
  type        = string
  default     = "SSD"

  validation {
    condition     = contains(["SSD", "HDD"], var.storage_type)
    error_message = "Storage type must be SSD or HDD."
  }
}

variable "per_unit_storage_throughput" {
  description = "Throughput (MB/s) per unit of storage (50, 100, 200 for SSD)"
  type        = number
  default     = 200

  validation {
    condition     = contains([50, 100, 200], var.per_unit_storage_throughput)
    error_message = "Per-unit storage throughput must be 50, 100, or 200 MB/s."
  }
}

variable "s3_models_bucket" {
  description = "S3 bucket path for FSx data repository (e.g., s3://bucket-name/models/)"
  type        = string
}

variable "create_s3_bucket" {
  description = "Create S3 bucket for FSx data repository"
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  description = "Number of days to retain automatic backups (0-90)"
  type        = number
  default     = 7

  validation {
    condition     = var.backup_retention_days >= 0 && var.backup_retention_days <= 90
    error_message = "Backup retention days must be between 0 and 90."
  }
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "alarm_actions" {
  description = "List of ARNs for CloudWatch alarm actions"
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

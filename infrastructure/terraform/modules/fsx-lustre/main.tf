# FSx Lustre File System Module
#
# Creates FSx Lustre file systems for high-performance model storage
#
# Features:
# - 1.2 TB storage per region (can scale to 100s of TB)
# - 1-2 GB/s throughput per instance
# - S3 data repository integration
# - Automatic file caching
# - Multi-AZ deployment for HA

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# FSx Lustre File System
resource "aws_fsx_lustre_file_system" "models" {
  # Storage configuration
  storage_capacity            = var.storage_capacity_gb
  subnet_ids                  = var.subnet_ids
  deployment_type             = var.deployment_type
  storage_type                = var.storage_type
  per_unit_storage_throughput = var.per_unit_storage_throughput

  # S3 data repository
  data_repository_association {
    data_repository_path = var.s3_models_bucket
    file_system_path     = "/models"

    # Import settings
    import_policy {
      events = ["NEW", "CHANGED", "DELETED"]
    }

    # Export settings
    export_policy {
      events = ["NEW", "CHANGED", "DELETED"]
    }
  }

  # Security
  security_group_ids = var.security_group_ids

  # Logging
  log_configuration {
    level       = "WARN_ERROR"
    destination = aws_cloudwatch_log_group.fsx.arn
  }

  # Backup
  automatic_backup_retention_days = var.backup_retention_days
  daily_automatic_backup_start_time = "03:00"  # 3 AM UTC
  copy_tags_to_backups = true

  # Tags
  tags = merge(
    var.tags,
    {
      Name = "${var.cluster_name}-fsx-${var.region_code}"
      Component = "storage"
      ManagedBy = "terraform"
    }
  )
}

# CloudWatch Log Group for FSx logs
resource "aws_cloudwatch_log_group" "fsx" {
  name              = "/aws/fsx/${var.cluster_name}-${var.region_code}"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

# CloudWatch Alarms

# Alarm: Low free storage
resource "aws_cloudwatch_metric_alarm" "low_storage" {
  alarm_name          = "${var.cluster_name}-fsx-${var.region_code}-low-storage"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "FreeStorageCapacity"
  namespace           = "AWS/FSx"
  period              = 300
  statistic           = "Average"
  threshold           = var.storage_capacity_gb * 1073741824 * 0.15  # 15% free
  alarm_description   = "FSx storage capacity below 15%"
  alarm_actions       = var.alarm_actions

  dimensions = {
    FileSystemId = aws_fsx_lustre_file_system.models.id
  }

  tags = var.tags
}

# Alarm: High network throughput (potential bottleneck)
resource "aws_cloudwatch_metric_alarm" "high_network_throughput" {
  alarm_name          = "${var.cluster_name}-fsx-${var.region_code}-high-throughput"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "DataReadBytes"
  namespace           = "AWS/FSx"
  period              = 60
  statistic           = "Sum"
  threshold           = 1000000000  # 1 GB/minute
  alarm_description   = "High FSx read throughput"
  alarm_actions       = var.alarm_actions

  dimensions = {
    FileSystemId = aws_fsx_lustre_file_system.models.id
  }

  tags = var.tags
}

# S3 Bucket for model storage (data repository)
resource "aws_s3_bucket" "models" {
  count  = var.create_s3_bucket ? 1 : 0
  bucket = "${var.cluster_name}-models-${var.region_code}-${data.aws_caller_identity.current.account_id}"

  tags = merge(
    var.tags,
    {
      Name = "${var.cluster_name}-models-${var.region_code}"
      Purpose = "FSx data repository"
    }
  )
}

# S3 bucket versioning
resource "aws_s3_bucket_versioning" "models" {
  count  = var.create_s3_bucket ? 1 : 0
  bucket = aws_s3_bucket.models[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

# S3 bucket encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "models" {
  count  = var.create_s3_bucket ? 1 : 0
  bucket = aws_s3_bucket.models[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# S3 bucket lifecycle
resource "aws_s3_bucket_lifecycle_configuration" "models" {
  count  = var.create_s3_bucket ? 1 : 0
  bucket = aws_s3_bucket.models[0].id

  rule {
    id     = "delete-old-versions"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# Data source for current AWS account
data "aws_caller_identity" "current" {}

# Outputs
output "file_system_id" {
  description = "FSx file system ID"
  value       = aws_fsx_lustre_file_system.models.id
}

output "dns_name" {
  description = "FSx DNS name for mounting"
  value       = aws_fsx_lustre_file_system.models.dns_name
}

output "mount_name" {
  description = "FSx mount name"
  value       = aws_fsx_lustre_file_system.models.mount_name
}

output "mount_command" {
  description = "Command to mount FSx on EC2 instances"
  value       = "sudo mount -t lustre ${aws_fsx_lustre_file_system.models.dns_name}@tcp:/${aws_fsx_lustre_file_system.models.mount_name} /fsx"
}

output "s3_bucket_name" {
  description = "S3 bucket name for model storage"
  value       = var.create_s3_bucket ? aws_s3_bucket.models[0].id : null
}

output "storage_capacity_gb" {
  description = "Storage capacity in GB"
  value       = var.storage_capacity_gb
}

output "throughput_mbps" {
  description = "Throughput capacity in MB/s"
  value       = var.per_unit_storage_throughput
}

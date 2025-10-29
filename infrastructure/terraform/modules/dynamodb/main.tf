# Multi-Region GPU Cluster - DynamoDB Global Tables Module
# Provides global state management across all regions

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# GPU Instance Registry Table
# Tracks all GPU instances across all regions
resource "aws_dynamodb_table" "gpu_instances" {
  name             = "${var.name_prefix}-gpu-instances"
  billing_mode     = "PAY_PER_REQUEST" # On-demand for variable load
  hash_key         = "instance_id"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "instance_id"
    type = "S"
  }

  attribute {
    name = "region"
    type = "S"
  }

  attribute {
    name = "model_pool"
    type = "S"
  }

  attribute {
    name = "state"
    type = "S"
  }

  # GSI for querying by region
  global_secondary_index {
    name            = "region-index"
    hash_key        = "region"
    range_key       = "instance_id"
    projection_type = "ALL"
  }

  # GSI for querying by model pool
  global_secondary_index {
    name            = "model-pool-index"
    hash_key        = "model_pool"
    range_key       = "instance_id"
    projection_type = "ALL"
  }

  # GSI for querying by state (e.g., find all "available" instances)
  global_secondary_index {
    name            = "state-index"
    hash_key        = "state"
    range_key       = "instance_id"
    projection_type = "ALL"
  }

  # Global Table Configuration
  dynamic "replica" {
    for_each = var.replica_regions
    content {
      region_name = replica.value
    }
  }

  # Point-in-time recovery for disaster recovery
  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  # Server-side encryption
  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  # TTL for auto-cleanup of old records
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = merge(
    var.tags,
    {
      Name  = "${var.name_prefix}-gpu-instances"
      Table = "gpu-instances"
    }
  )
}

# Routing State Table
# Stores current routing scores and health status
resource "aws_dynamodb_table" "routing_state" {
  name             = "${var.name_prefix}-routing-state"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "instance_id"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "instance_id"
    type = "S"
  }

  attribute {
    name = "region"
    type = "S"
  }

  attribute {
    name = "routing_score"
    type = "N"
  }

  # GSI for finding best instances by region
  global_secondary_index {
    name            = "region-score-index"
    hash_key        = "region"
    range_key       = "routing_score"
    projection_type = "ALL"
  }

  # Global Table Configuration
  dynamic "replica" {
    for_each = var.replica_regions
    content {
      region_name = replica.value
    }
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = merge(
    var.tags,
    {
      Name  = "${var.name_prefix}-routing-state"
      Table = "routing-state"
    }
  )
}

# Autoscaling State Table
# Tracks capacity and scaling events
resource "aws_dynamodb_table" "autoscaling_state" {
  name             = "${var.name_prefix}-autoscaling-state"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "model_pool"
  range_key        = "timestamp"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "model_pool"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "N"
  }

  attribute {
    name = "region"
    type = "S"
  }

  # GSI for querying by region
  global_secondary_index {
    name            = "region-timestamp-index"
    hash_key        = "region"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  # Global Table Configuration
  dynamic "replica" {
    for_each = var.replica_regions
    content {
      region_name = replica.value
    }
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = merge(
    var.tags,
    {
      Name  = "${var.name_prefix}-autoscaling-state"
      Table = "autoscaling-state"
    }
  )
}

# Cleanup Validation Table (Car Wash)
# Tracks security cleanup validation before instance reuse
resource "aws_dynamodb_table" "cleanup_validation" {
  name             = "${var.name_prefix}-cleanup-validation"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "instance_id"
  range_key        = "validation_timestamp"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "instance_id"
    type = "S"
  }

  attribute {
    name = "validation_timestamp"
    type = "N"
  }

  attribute {
    name = "validation_status"
    type = "S"
  }

  # GSI for finding failed validations
  global_secondary_index {
    name            = "status-timestamp-index"
    hash_key        = "validation_status"
    range_key       = "validation_timestamp"
    projection_type = "ALL"
  }

  # Global Table Configuration
  dynamic "replica" {
    for_each = var.replica_regions
    content {
      region_name = replica.value
    }
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = merge(
    var.tags,
    {
      Name  = "${var.name_prefix}-cleanup-validation"
      Table = "cleanup-validation"
    }
  )
}

# Metrics Table
# Stores aggregated metrics for monitoring and alerting
resource "aws_dynamodb_table" "metrics" {
  name             = "${var.name_prefix}-metrics"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "metric_name"
  range_key        = "timestamp"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "metric_name"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "N"
  }

  attribute {
    name = "region"
    type = "S"
  }

  # GSI for querying by region
  global_secondary_index {
    name            = "region-timestamp-index"
    hash_key        = "region"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  # Global Table Configuration
  dynamic "replica" {
    for_each = var.replica_regions
    content {
      region_name = replica.value
    }
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = merge(
    var.tags,
    {
      Name  = "${var.name_prefix}-metrics"
      Table = "metrics"
    }
  )
}

# CloudWatch Alarms for DynamoDB
resource "aws_cloudwatch_metric_alarm" "user_errors" {
  count = var.enable_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-dynamodb-user-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "UserErrors"
  namespace           = "AWS/DynamoDB"
  period              = "300"
  statistic           = "Sum"
  threshold           = "10"
  alarm_description   = "DynamoDB user errors exceed threshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TableName = aws_dynamodb_table.gpu_instances.name
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "system_errors" {
  count = var.enable_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-dynamodb-system-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "SystemErrors"
  namespace           = "AWS/DynamoDB"
  period              = "60"
  statistic           = "Sum"
  threshold           = "0"
  alarm_description   = "DynamoDB system errors detected"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TableName = aws_dynamodb_table.gpu_instances.name
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "replication_latency" {
  count = var.enable_cloudwatch_alarms && length(var.replica_regions) > 0 ? 1 : 0

  alarm_name          = "${var.name_prefix}-dynamodb-replication-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "ReplicationLatency"
  namespace           = "AWS/DynamoDB"
  period              = "300"
  statistic           = "Average"
  threshold           = "2000" # 2 seconds
  alarm_description   = "DynamoDB replication latency too high"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TableName            = aws_dynamodb_table.gpu_instances.name
    ReceivingRegion      = var.replica_regions[0]
  }

  tags = var.tags
}

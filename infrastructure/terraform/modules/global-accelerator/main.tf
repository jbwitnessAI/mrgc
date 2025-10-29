# Multi-Region GPU Cluster - Global Accelerator Module
# Provides static anycast IPs and intelligent routing across regions

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Global Accelerator
resource "aws_globalaccelerator_accelerator" "main" {
  name            = var.name
  ip_address_type = "IPV4"
  enabled         = var.enabled

  attributes {
    flow_logs_enabled   = var.flow_logs_enabled
    flow_logs_s3_bucket = var.flow_logs_s3_bucket
    flow_logs_s3_prefix = var.flow_logs_s3_prefix
  }

  tags = var.tags
}

# Listener for HTTPS traffic (port 443)
resource "aws_globalaccelerator_listener" "https" {
  accelerator_arn = aws_globalaccelerator_accelerator.main.id
  protocol        = "TCP"

  port_range {
    from_port = 443
    to_port   = 443
  }

  client_affinity = var.client_affinity
}

# Listener for HTTP traffic (port 8080)
resource "aws_globalaccelerator_listener" "http" {
  count = var.enable_http_listener ? 1 : 0

  accelerator_arn = aws_globalaccelerator_accelerator.main.id
  protocol        = "TCP"

  port_range {
    from_port = 8080
    to_port   = 8080
  }

  client_affinity = var.client_affinity
}

# Endpoint Group for us-east-1
resource "aws_globalaccelerator_endpoint_group" "use1" {
  count = contains(var.regions, "us-east-1") ? 1 : 0

  listener_arn = aws_globalaccelerator_listener.https.id

  endpoint_group_region = "us-east-1"
  traffic_dial_percentage = lookup(
    var.traffic_dial_percentages,
    "us-east-1",
    100
  )

  health_check_interval_seconds = var.health_check_interval_seconds
  health_check_protocol         = var.health_check_protocol
  health_check_port             = var.health_check_port
  health_check_path             = var.health_check_path
  threshold_count               = var.health_check_threshold_count

  endpoint_configuration {
    endpoint_id = var.endpoint_arns["us-east-1"]
    weight      = lookup(var.endpoint_weights, "us-east-1", 128)
    client_ip_preservation_enabled = false # NLB doesn't support this
  }
}

# Endpoint Group for us-east-2
resource "aws_globalaccelerator_endpoint_group" "use2" {
  count = contains(var.regions, "us-east-2") ? 1 : 0

  listener_arn = aws_globalaccelerator_listener.https.id

  endpoint_group_region = "us-east-2"
  traffic_dial_percentage = lookup(
    var.traffic_dial_percentages,
    "us-east-2",
    100
  )

  health_check_interval_seconds = var.health_check_interval_seconds
  health_check_protocol         = var.health_check_protocol
  health_check_port             = var.health_check_port
  health_check_path             = var.health_check_path
  threshold_count               = var.health_check_threshold_count

  endpoint_configuration {
    endpoint_id = var.endpoint_arns["us-east-2"]
    weight      = lookup(var.endpoint_weights, "us-east-2", 128)
    client_ip_preservation_enabled = false
  }
}

# Endpoint Group for us-west-2
resource "aws_globalaccelerator_endpoint_group" "usw2" {
  count = contains(var.regions, "us-west-2") ? 1 : 0

  listener_arn = aws_globalaccelerator_listener.https.id

  endpoint_group_region = "us-west-2"
  traffic_dial_percentage = lookup(
    var.traffic_dial_percentages,
    "us-west-2",
    100
  )

  health_check_interval_seconds = var.health_check_interval_seconds
  health_check_protocol         = var.health_check_protocol
  health_check_port             = var.health_check_port
  health_check_path             = var.health_check_path
  threshold_count               = var.health_check_threshold_count

  endpoint_configuration {
    endpoint_id = var.endpoint_arns["us-west-2"]
    weight      = lookup(var.endpoint_weights, "us-west-2", 128)
    client_ip_preservation_enabled = false
  }
}

# HTTP Endpoint Groups (if HTTP listener enabled)
resource "aws_globalaccelerator_endpoint_group" "use1_http" {
  count = var.enable_http_listener && contains(var.regions, "us-east-1") ? 1 : 0

  listener_arn = aws_globalaccelerator_listener.http[0].id

  endpoint_group_region = "us-east-1"
  traffic_dial_percentage = lookup(
    var.traffic_dial_percentages,
    "us-east-1",
    100
  )

  health_check_interval_seconds = var.health_check_interval_seconds
  health_check_protocol         = "HTTP"
  health_check_port             = 8080
  health_check_path             = "/health"
  threshold_count               = var.health_check_threshold_count

  endpoint_configuration {
    endpoint_id = var.endpoint_arns["us-east-1"]
    weight      = lookup(var.endpoint_weights, "us-east-1", 128)
    client_ip_preservation_enabled = false
  }
}

resource "aws_globalaccelerator_endpoint_group" "use2_http" {
  count = var.enable_http_listener && contains(var.regions, "us-east-2") ? 1 : 0

  listener_arn = aws_globalaccelerator_listener.http[0].id

  endpoint_group_region = "us-east-2"
  traffic_dial_percentage = lookup(
    var.traffic_dial_percentages,
    "us-east-2",
    100
  )

  health_check_interval_seconds = var.health_check_interval_seconds
  health_check_protocol         = "HTTP"
  health_check_port             = 8080
  health_check_path             = "/health"
  threshold_count               = var.health_check_threshold_count

  endpoint_configuration {
    endpoint_id = var.endpoint_arns["us-east-2"]
    weight      = lookup(var.endpoint_weights, "us-east-2", 128)
    client_ip_preservation_enabled = false
  }
}

resource "aws_globalaccelerator_endpoint_group" "usw2_http" {
  count = var.enable_http_listener && contains(var.regions, "us-west-2") ? 1 : 0

  listener_arn = aws_globalaccelerator_listener.http[0].id

  endpoint_group_region = "us-west-2"
  traffic_dial_percentage = lookup(
    var.traffic_dial_percentages,
    "us-west-2",
    100
  )

  health_check_interval_seconds = var.health_check_interval_seconds
  health_check_protocol         = "HTTP"
  health_check_port             = 8080
  health_check_path             = "/health"
  threshold_count               = var.health_check_threshold_count

  endpoint_configuration {
    endpoint_id = var.endpoint_arns["us-west-2"]
    weight      = lookup(var.endpoint_weights, "us-west-2", 128)
    client_ip_preservation_enabled = false
  }
}

# CloudWatch Alarms for Global Accelerator
resource "aws_cloudwatch_metric_alarm" "unhealthy_endpoints" {
  count = var.enable_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.name}-unhealthy-endpoints"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "UnhealthyEndpointCount"
  namespace           = "AWS/GlobalAccelerator"
  period              = "60"
  statistic           = "Average"
  threshold           = "0"
  alarm_description   = "Global Accelerator has unhealthy endpoints"
  treat_missing_data  = "notBreaching"

  dimensions = {
    Accelerator = aws_globalaccelerator_accelerator.main.id
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "new_flow_count" {
  count = var.enable_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.name}-high-new-flows"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "NewFlowCount"
  namespace           = "AWS/GlobalAccelerator"
  period              = "300"
  statistic           = "Sum"
  threshold           = var.max_new_flows_threshold
  alarm_description   = "Global Accelerator new flow count is high"
  treat_missing_data  = "notBreaching"

  dimensions = {
    Accelerator = aws_globalaccelerator_accelerator.main.id
  }

  tags = var.tags
}

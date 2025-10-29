# Multi-Region GPU Cluster - Network Load Balancer Module
# Provides regional entry point for Global Accelerator

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Network Load Balancer
resource "aws_lb" "nlb" {
  name               = "${var.name_prefix}-nlb"
  internal           = var.internal
  load_balancer_type = "network"
  subnets            = var.subnet_ids

  enable_deletion_protection       = var.enable_deletion_protection
  enable_cross_zone_load_balancing = var.enable_cross_zone_load_balancing

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-nlb"
    }
  )
}

# Target Group for Regional Router (ECS Fargate)
resource "aws_lb_target_group" "regional_router" {
  name        = "${var.name_prefix}-router-tg"
  port        = 443
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "ip" # For ECS Fargate

  health_check {
    enabled             = true
    protocol            = "TCP"
    port                = "traffic-port"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    interval            = 30
  }

  deregistration_delay = 30

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-router-tg"
    }
  )
}

# Listener for HTTPS (port 443)
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.nlb.arn
  port              = 443
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.regional_router.arn
  }

  tags = var.tags
}

# Target Group for HTTP (port 8080) - for health checks and non-encrypted traffic
resource "aws_lb_target_group" "http" {
  count = var.enable_http_listener ? 1 : 0

  name        = "${var.name_prefix}-http-tg"
  port        = 8080
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    protocol            = "HTTP"
    port                = "traffic-port"
    path                = "/health"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    interval            = 30
  }

  deregistration_delay = 30

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-http-tg"
    }
  )
}

# Listener for HTTP (port 8080)
resource "aws_lb_listener" "http" {
  count = var.enable_http_listener ? 1 : 0

  load_balancer_arn = aws_lb.nlb.arn
  port              = 8080
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.http[0].arn
  }

  tags = var.tags
}

# CloudWatch Alarms for NLB
resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  count = var.enable_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-nlb-unhealthy-hosts"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/NetworkELB"
  period              = "60"
  statistic           = "Average"
  threshold           = "0"
  alarm_description   = "NLB has unhealthy hosts"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.nlb.arn_suffix
    TargetGroup  = aws_lb_target_group.regional_router.arn_suffix
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "active_connections" {
  count = var.enable_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-nlb-high-connections"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "ActiveFlowCount"
  namespace           = "AWS/NetworkELB"
  period              = "300"
  statistic           = "Sum"
  threshold           = var.max_active_connections
  alarm_description   = "NLB has high number of active connections"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.nlb.arn_suffix
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "target_response_time" {
  count = var.enable_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-nlb-high-response-time"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/NetworkELB"
  period              = "60"
  statistic           = "Average"
  threshold           = var.max_response_time_seconds
  alarm_description   = "NLB target response time is high"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.nlb.arn_suffix
  }

  tags = var.tags
}

# VPC Endpoint Service (for PrivateLink - Feature 2B)
resource "aws_vpc_endpoint_service" "nlb" {
  count = var.enable_privatelink_service ? 1 : 0

  acceptance_required        = var.privatelink_acceptance_required
  network_load_balancer_arns = [aws_lb.nlb.arn]

  # Allow specific principals (AWS accounts) to connect
  allowed_principals = var.privatelink_allowed_principals

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-privatelink-service"
    }
  )
}

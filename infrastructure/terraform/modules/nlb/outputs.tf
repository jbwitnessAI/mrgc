# NLB Module Outputs

output "nlb_arn" {
  description = "ARN of the Network Load Balancer"
  value       = aws_lb.nlb.arn
}

output "nlb_dns_name" {
  description = "DNS name of the Network Load Balancer"
  value       = aws_lb.nlb.dns_name
}

output "nlb_zone_id" {
  description = "Zone ID of the Network Load Balancer"
  value       = aws_lb.nlb.zone_id
}

output "nlb_arn_suffix" {
  description = "ARN suffix for CloudWatch metrics"
  value       = aws_lb.nlb.arn_suffix
}

output "target_group_arn" {
  description = "ARN of the HTTPS target group (port 443)"
  value       = aws_lb_target_group.regional_router.arn
}

output "target_group_arn_suffix" {
  description = "ARN suffix of the target group"
  value       = aws_lb_target_group.regional_router.arn_suffix
}

output "http_target_group_arn" {
  description = "ARN of the HTTP target group (port 8080)"
  value       = var.enable_http_listener ? aws_lb_target_group.http[0].arn : null
}

output "listener_arn_https" {
  description = "ARN of the HTTPS listener (port 443)"
  value       = aws_lb_listener.https.arn
}

output "listener_arn_http" {
  description = "ARN of the HTTP listener (port 8080)"
  value       = var.enable_http_listener ? aws_lb_listener.http[0].arn : null
}

output "vpc_endpoint_service_name" {
  description = "VPC Endpoint Service name for PrivateLink"
  value       = var.enable_privatelink_service ? aws_vpc_endpoint_service.nlb[0].service_name : null
}

output "vpc_endpoint_service_id" {
  description = "VPC Endpoint Service ID"
  value       = var.enable_privatelink_service ? aws_vpc_endpoint_service.nlb[0].id : null
}

# Global Accelerator Module Outputs

output "accelerator_id" {
  description = "ID of the Global Accelerator"
  value       = aws_globalaccelerator_accelerator.main.id
}

output "accelerator_arn" {
  description = "ARN of the Global Accelerator"
  value       = aws_globalaccelerator_accelerator.main.id # In AWS, ID and ARN are same for Global Accelerator
}

output "accelerator_dns_name" {
  description = "DNS name of the Global Accelerator"
  value       = aws_globalaccelerator_accelerator.main.dns_name
}

output "accelerator_hosted_zone_id" {
  description = "Hosted zone ID of the Global Accelerator"
  value       = aws_globalaccelerator_accelerator.main.hosted_zone_id
}

output "ip_sets" {
  description = "List of IP address sets (anycast IPs)"
  value       = aws_globalaccelerator_accelerator.main.ip_sets
}

output "static_ip_addresses" {
  description = "List of static anycast IP addresses"
  value       = flatten([
    for ip_set in aws_globalaccelerator_accelerator.main.ip_sets : ip_set.ip_addresses
  ])
}

output "listener_arn_https" {
  description = "ARN of the HTTPS listener (port 443)"
  value       = aws_globalaccelerator_listener.https.id
}

output "listener_arn_http" {
  description = "ARN of the HTTP listener (port 8080)"
  value       = var.enable_http_listener ? aws_globalaccelerator_listener.http[0].id : null
}

output "endpoint_group_arns" {
  description = "Map of region -> endpoint group ARN"
  value = {
    "us-east-1" = contains(var.regions, "us-east-1") ? aws_globalaccelerator_endpoint_group.use1[0].id : null
    "us-east-2" = contains(var.regions, "us-east-2") ? aws_globalaccelerator_endpoint_group.use2[0].id : null
    "us-west-2" = contains(var.regions, "us-west-2") ? aws_globalaccelerator_endpoint_group.usw2[0].id : null
  }
}

output "summary" {
  description = "Summary of Global Accelerator configuration for easy reference"
  value = {
    name           = var.name
    dns_name       = aws_globalaccelerator_accelerator.main.dns_name
    static_ips     = flatten([
      for ip_set in aws_globalaccelerator_accelerator.main.ip_sets : ip_set.ip_addresses
    ])
    regions        = var.regions
    enabled        = var.enabled
  }
}

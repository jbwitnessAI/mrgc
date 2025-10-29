# Transit Gateway Module Outputs

output "transit_gateway_id" {
  description = "Transit Gateway ID"
  value       = aws_ec2_transit_gateway.main.id
}

output "transit_gateway_arn" {
  description = "Transit Gateway ARN"
  value       = aws_ec2_transit_gateway.main.arn
}

output "transit_gateway_owner_id" {
  description = "Transit Gateway owner account ID"
  value       = aws_ec2_transit_gateway.main.owner_id
}

output "transit_gateway_association_default_route_table_id" {
  description = "Transit Gateway default association route table ID"
  value       = aws_ec2_transit_gateway.main.association_default_route_table_id
}

output "transit_gateway_propagation_default_route_table_id" {
  description = "Transit Gateway default propagation route table ID"
  value       = aws_ec2_transit_gateway.main.propagation_default_route_table_id
}

output "vpc_attachment_id" {
  description = "VPC attachment ID"
  value       = aws_ec2_transit_gateway_vpc_attachment.main.id
}

output "custom_route_table_id" {
  description = "Custom Transit Gateway route table ID (if created)"
  value       = var.create_custom_route_table ? aws_ec2_transit_gateway_route_table.main[0].id : null
}

output "ram_resource_share_arn" {
  description = "RAM Resource Share ARN (if created)"
  value       = length(var.ram_principals) > 0 ? aws_ram_resource_share.tgw[0].arn : null
}

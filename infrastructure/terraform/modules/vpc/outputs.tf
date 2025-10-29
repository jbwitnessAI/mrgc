# VPC Module Outputs

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "vpc_cidr" {
  description = "VPC CIDR block"
  value       = aws_vpc.main.cidr_block
}

output "internet_gateway_id" {
  description = "Internet Gateway ID"
  value       = aws_internet_gateway.main.id
}

output "public_subnet_ids" {
  description = "List of public subnet IDs"
  value       = aws_subnet.public[*].id
}

output "public_subnet_cidrs" {
  description = "List of public subnet CIDR blocks"
  value       = aws_subnet.public[*].cidr_block
}

output "private_subnet_ids" {
  description = "List of private subnet IDs (for GPU instances)"
  value       = aws_subnet.private[*].id
}

output "private_subnet_cidrs" {
  description = "List of private subnet CIDR blocks"
  value       = aws_subnet.private[*].cidr_block
}

output "fsx_subnet_ids" {
  description = "List of FSx subnet IDs"
  value       = aws_subnet.fsx[*].id
}

output "fsx_subnet_cidrs" {
  description = "List of FSx subnet CIDR blocks"
  value       = aws_subnet.fsx[*].cidr_block
}

output "tgw_subnet_ids" {
  description = "List of Transit Gateway subnet IDs"
  value       = aws_subnet.tgw[*].id
}

output "tgw_subnet_cidrs" {
  description = "List of Transit Gateway subnet CIDR blocks"
  value       = aws_subnet.tgw[*].cidr_block
}

output "nat_gateway_ids" {
  description = "List of NAT Gateway IDs"
  value       = var.nat_gateway_enabled ? aws_nat_gateway.main[*].id : []
}

output "nat_gateway_ips" {
  description = "List of NAT Gateway public IPs"
  value       = var.nat_gateway_enabled ? aws_eip.nat[*].public_ip : []
}

output "public_route_table_id" {
  description = "Public route table ID"
  value       = aws_route_table.public.id
}

output "private_route_table_ids" {
  description = "List of private route table IDs"
  value       = aws_route_table.private[*].id
}

output "fsx_route_table_id" {
  description = "FSx route table ID"
  value       = aws_route_table.fsx.id
}

output "vpc_endpoint_s3_id" {
  description = "S3 VPC endpoint ID"
  value       = var.vpc_endpoints_enabled ? aws_vpc_endpoint.s3[0].id : null
}

output "vpc_endpoint_dynamodb_id" {
  description = "DynamoDB VPC endpoint ID"
  value       = var.vpc_endpoints_enabled ? aws_vpc_endpoint.dynamodb[0].id : null
}

output "vpc_endpoint_kms_id" {
  description = "KMS VPC endpoint ID"
  value       = var.vpc_endpoints_enabled ? aws_vpc_endpoint.kms[0].id : null
}

output "vpc_endpoint_security_group_id" {
  description = "Security group ID for VPC endpoints"
  value       = var.vpc_endpoints_enabled ? aws_security_group.vpc_endpoints[0].id : null
}

output "flow_logs_log_group_name" {
  description = "CloudWatch Log Group name for VPC Flow Logs"
  value       = var.flow_logs_enabled ? aws_cloudwatch_log_group.flow_logs[0].name : null
}

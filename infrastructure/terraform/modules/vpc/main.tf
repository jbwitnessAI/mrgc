# Multi-Region GPU Cluster - VPC Module
# Creates VPC with public, private, FSx, and Transit Gateway subnets

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# VPC
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(
    var.tags,
    {
      Name   = "${var.name_prefix}-vpc"
      Region = var.region
    }
  )
}

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-igw"
    }
  )
}

# Public Subnets
resource "aws_subnet" "public" {
  count = length(var.public_subnets)

  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnets[count.index].cidr
  availability_zone       = var.public_subnets[count.index].az
  map_public_ip_on_launch = true

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-${var.public_subnets[count.index].name}"
      Type = "public"
    }
  )
}

# Private Subnets (for GPU instances)
resource "aws_subnet" "private" {
  count = length(var.private_subnets)

  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnets[count.index].cidr
  availability_zone = var.private_subnets[count.index].az

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-${var.private_subnets[count.index].name}"
      Type = "private"
      Role = "gpu-instances"
    }
  )
}

# FSx Lustre Subnets
resource "aws_subnet" "fsx" {
  count = length(var.fsx_subnets)

  vpc_id            = aws_vpc.main.id
  cidr_block        = var.fsx_subnets[count.index].cidr
  availability_zone = var.fsx_subnets[count.index].az

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-${var.fsx_subnets[count.index].name}"
      Type = "fsx"
      Role = "storage"
    }
  )
}

# Transit Gateway Subnets
resource "aws_subnet" "tgw" {
  count = length(var.tgw_subnets)

  vpc_id            = aws_vpc.main.id
  cidr_block        = var.tgw_subnets[count.index].cidr
  availability_zone = var.tgw_subnets[count.index].az

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-${var.tgw_subnets[count.index].name}"
      Type = "tgw"
      Role = "transit-gateway"
    }
  )
}

# Elastic IPs for NAT Gateways (one per AZ for HA)
resource "aws_eip" "nat" {
  count  = var.nat_gateway_enabled && var.nat_gateway_ha ? length(var.public_subnets) : (var.nat_gateway_enabled ? 1 : 0)
  domain = "vpc"

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-nat-eip-${count.index + 1}"
    }
  )

  depends_on = [aws_internet_gateway.main]
}

# NAT Gateways (one per AZ for HA, or single for cost optimization)
resource "aws_nat_gateway" "main" {
  count = var.nat_gateway_enabled && var.nat_gateway_ha ? length(var.public_subnets) : (var.nat_gateway_enabled ? 1 : 0)

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-nat-${count.index + 1}"
    }
  )

  depends_on = [aws_internet_gateway.main]
}

# Public Route Table
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-public-rt"
    }
  )
}

# Public Route Table Associations
resource "aws_route_table_association" "public" {
  count = length(aws_subnet.public)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Private Route Tables (one per AZ if HA NAT, otherwise single)
resource "aws_route_table" "private" {
  count = var.nat_gateway_enabled && var.nat_gateway_ha ? length(var.private_subnets) : 1

  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = var.nat_gateway_ha ? aws_nat_gateway.main[count.index].id : (var.nat_gateway_enabled ? aws_nat_gateway.main[0].id : null)
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-private-rt-${count.index + 1}"
    }
  )
}

# Private Route Table Associations
resource "aws_route_table_association" "private" {
  count = length(aws_subnet.private)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = var.nat_gateway_ha ? aws_route_table.private[count.index].id : aws_route_table.private[0].id
}

# FSx Route Table
resource "aws_route_table" "fsx" {
  vpc_id = aws_vpc.main.id

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-fsx-rt"
    }
  )
}

# FSx Route Table Associations
resource "aws_route_table_association" "fsx" {
  count = length(aws_subnet.fsx)

  subnet_id      = aws_subnet.fsx[count.index].id
  route_table_id = aws_route_table.fsx.id
}

# VPC Flow Logs
resource "aws_flow_log" "main" {
  count = var.flow_logs_enabled ? 1 : 0

  vpc_id          = aws_vpc.main.id
  traffic_type    = "ALL"
  iam_role_arn    = var.flow_logs_enabled ? aws_iam_role.flow_logs[0].arn : null
  log_destination = var.flow_logs_enabled ? aws_cloudwatch_log_group.flow_logs[0].arn : null

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-flow-logs"
    }
  )
}

# CloudWatch Log Group for Flow Logs
resource "aws_cloudwatch_log_group" "flow_logs" {
  count = var.flow_logs_enabled ? 1 : 0

  name              = "/aws/vpc/${var.name_prefix}-flow-logs"
  retention_in_days = var.flow_logs_retention_days

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-flow-logs"
    }
  )
}

# IAM Role for Flow Logs
resource "aws_iam_role" "flow_logs" {
  count = var.flow_logs_enabled ? 1 : 0

  name = "${var.name_prefix}-flow-logs-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "vpc-flow-logs.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

# IAM Policy for Flow Logs
resource "aws_iam_role_policy" "flow_logs" {
  count = var.flow_logs_enabled ? 1 : 0

  name = "${var.name_prefix}-flow-logs-policy"
  role = aws_iam_role.flow_logs[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams"
        ]
        Effect   = "Allow"
        Resource = "*"
      }
    ]
  })
}

# VPC Endpoints - S3 (Gateway)
resource "aws_vpc_endpoint" "s3" {
  count = var.vpc_endpoints_enabled ? 1 : 0

  vpc_id       = aws_vpc.main.id
  service_name = "com.amazonaws.${var.region}.s3"

  route_table_ids = concat(
    [aws_route_table.public.id],
    aws_route_table.private[*].id,
    [aws_route_table.fsx.id]
  )

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-s3-endpoint"
    }
  )
}

# VPC Endpoints - DynamoDB (Gateway)
resource "aws_vpc_endpoint" "dynamodb" {
  count = var.vpc_endpoints_enabled ? 1 : 0

  vpc_id       = aws_vpc.main.id
  service_name = "com.amazonaws.${var.region}.dynamodb"

  route_table_ids = concat(
    [aws_route_table.public.id],
    aws_route_table.private[*].id
  )

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-dynamodb-endpoint"
    }
  )
}

# Security Group for VPC Endpoints
resource "aws_security_group" "vpc_endpoints" {
  count = var.vpc_endpoints_enabled ? 1 : 0

  name_prefix = "${var.name_prefix}-vpce-"
  description = "Security group for VPC endpoints"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-vpce-sg"
    }
  )
}

# VPC Endpoints - KMS (Interface)
resource "aws_vpc_endpoint" "kms" {
  count = var.vpc_endpoints_enabled ? 1 : 0

  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.kms"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-kms-endpoint"
    }
  )
}

# VPC Endpoints - EC2 (Interface)
resource "aws_vpc_endpoint" "ec2" {
  count = var.vpc_endpoints_enabled ? 1 : 0

  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.ec2"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-ec2-endpoint"
    }
  )
}

# VPC Endpoints - CloudWatch Logs (Interface)
resource "aws_vpc_endpoint" "logs" {
  count = var.vpc_endpoints_enabled ? 1 : 0

  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-logs-endpoint"
    }
  )
}

# VPC Endpoints - CloudWatch Monitoring (Interface)
resource "aws_vpc_endpoint" "monitoring" {
  count = var.vpc_endpoints_enabled ? 1 : 0

  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.monitoring"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-monitoring-endpoint"
    }
  )
}

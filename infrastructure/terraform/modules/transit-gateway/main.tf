# Multi-Region GPU Cluster - Transit Gateway Module
# Enables cross-region private networking

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Transit Gateway (one per region)
resource "aws_ec2_transit_gateway" "main" {
  description                     = "Transit Gateway for ${var.region} - Multi-Region GPU Cluster"
  amazon_side_asn                 = var.amazon_side_asn
  auto_accept_shared_attachments  = var.auto_accept_shared_attachments ? "enable" : "disable"
  default_route_table_association = var.default_route_table_association ? "enable" : "disable"
  default_route_table_propagation = var.default_route_table_propagation ? "enable" : "disable"
  dns_support                     = "enable"
  vpn_ecmp_support                = "enable"
  multicast_support               = "disable"

  tags = merge(
    var.tags,
    {
      Name   = "${var.name_prefix}-tgw"
      Region = var.region
    }
  )
}

# VPC Attachment to Transit Gateway
resource "aws_ec2_transit_gateway_vpc_attachment" "main" {
  subnet_ids                                      = var.tgw_subnet_ids
  transit_gateway_id                              = aws_ec2_transit_gateway.main.id
  vpc_id                                          = var.vpc_id
  dns_support                                     = "enable"
  ipv6_support                                    = "disable"
  appliance_mode_support                          = "disable"
  transit_gateway_default_route_table_association = var.default_route_table_association
  transit_gateway_default_route_table_propagation = var.default_route_table_propagation

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-tgw-attachment"
    }
  )
}

# Transit Gateway Route Table (custom, if not using default)
resource "aws_ec2_transit_gateway_route_table" "main" {
  count = var.create_custom_route_table ? 1 : 0

  transit_gateway_id = aws_ec2_transit_gateway.main.id

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-tgw-rt"
    }
  )
}

# Route Table Association (if using custom route table)
resource "aws_ec2_transit_gateway_route_table_association" "main" {
  count = var.create_custom_route_table ? 1 : 0

  transit_gateway_attachment_id  = aws_ec2_transit_gateway_vpc_attachment.main.id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.main[0].id
}

# Add routes to VPC route tables pointing to Transit Gateway
resource "aws_route" "private_to_tgw" {
  count = length(var.private_route_table_ids)

  route_table_id         = var.private_route_table_ids[count.index]
  destination_cidr_block = var.cross_region_cidr_block
  transit_gateway_id     = aws_ec2_transit_gateway.main.id

  depends_on = [aws_ec2_transit_gateway_vpc_attachment.main]
}

# Add routes to FSx route table pointing to Transit Gateway
resource "aws_route" "fsx_to_tgw" {
  count = var.fsx_route_table_id != null ? 1 : 0

  route_table_id         = var.fsx_route_table_id
  destination_cidr_block = var.cross_region_cidr_block
  transit_gateway_id     = aws_ec2_transit_gateway.main.id

  depends_on = [aws_ec2_transit_gateway_vpc_attachment.main]
}

# RAM (Resource Access Manager) Share for cross-account TGW access (optional)
resource "aws_ram_resource_share" "tgw" {
  count = length(var.ram_principals) > 0 ? 1 : 0

  name                      = "${var.name_prefix}-tgw-share"
  allow_external_principals = false

  tags = merge(
    var.tags,
    {
      Name = "${var.name_prefix}-tgw-share"
    }
  )
}

resource "aws_ram_resource_association" "tgw" {
  count = length(var.ram_principals) > 0 ? 1 : 0

  resource_arn       = aws_ec2_transit_gateway.main.arn
  resource_share_arn = aws_ram_resource_share.tgw[0].arn
}

resource "aws_ram_principal_association" "tgw" {
  count = length(var.ram_principals)

  principal          = var.ram_principals[count.index]
  resource_share_arn = aws_ram_resource_share.tgw[0].arn
}

# CloudWatch Alarms for Transit Gateway
resource "aws_cloudwatch_metric_alarm" "tgw_packet_drop" {
  count = var.enable_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-tgw-packet-drop"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "PacketDropCountBlackhole"
  namespace           = "AWS/TransitGateway"
  period              = "300"
  statistic           = "Sum"
  threshold           = "100"
  alarm_description   = "Transit Gateway packet drops due to blackhole routes"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TransitGateway = aws_ec2_transit_gateway.main.id
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "tgw_bytes_in" {
  count = var.enable_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-tgw-high-bytes-in"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "BytesIn"
  namespace           = "AWS/TransitGateway"
  period              = "300"
  statistic           = "Sum"
  threshold           = var.bytes_in_threshold
  alarm_description   = "Transit Gateway high inbound traffic"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TransitGateway = aws_ec2_transit_gateway.main.id
  }

  tags = var.tags
}

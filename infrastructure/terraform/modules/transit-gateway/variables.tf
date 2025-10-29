# Transit Gateway Module Variables

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID to attach to Transit Gateway"
  type        = string
}

variable "tgw_subnet_ids" {
  description = "List of subnet IDs for Transit Gateway attachment"
  type        = list(string)
}

variable "private_route_table_ids" {
  description = "List of private route table IDs to add TGW routes"
  type        = list(string)
  default     = []
}

variable "fsx_route_table_id" {
  description = "FSx route table ID to add TGW routes"
  type        = string
  default     = null
}

variable "cross_region_cidr_block" {
  description = "CIDR block for cross-region traffic (use 10.66.0.0/16 for all regions)"
  type        = string
  default     = "10.66.0.0/16"
}

variable "amazon_side_asn" {
  description = "Private Autonomous System Number (ASN) for the Amazon side of the BGP session"
  type        = number
  default     = 64512
}

variable "auto_accept_shared_attachments" {
  description = "Automatically accept cross-account attachments"
  type        = bool
  default     = true
}

variable "default_route_table_association" {
  description = "Enable default route table association"
  type        = bool
  default     = true
}

variable "default_route_table_propagation" {
  description = "Enable default route table propagation"
  type        = bool
  default     = true
}

variable "create_custom_route_table" {
  description = "Create a custom Transit Gateway route table"
  type        = bool
  default     = false
}

variable "ram_principals" {
  description = "List of principals (AWS account IDs or Organization ARNs) to share TGW with"
  type        = list(string)
  default     = []
}

variable "enable_cloudwatch_alarms" {
  description = "Enable CloudWatch alarms for Transit Gateway"
  type        = bool
  default     = true
}

variable "bytes_in_threshold" {
  description = "Threshold for BytesIn alarm (in bytes)"
  type        = number
  default     = 10737418240 # 10 GB
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

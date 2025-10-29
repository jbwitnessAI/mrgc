# VPC Module Variables

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
}

variable "public_subnets" {
  description = "List of public subnet configurations"
  type = list(object({
    cidr = string
    az   = string
    name = string
  }))
}

variable "private_subnets" {
  description = "List of private subnet configurations"
  type = list(object({
    cidr = string
    az   = string
    name = string
  }))
}

variable "fsx_subnets" {
  description = "List of FSx subnet configurations"
  type = list(object({
    cidr = string
    az   = string
    name = string
  }))
}

variable "tgw_subnets" {
  description = "List of Transit Gateway subnet configurations"
  type = list(object({
    cidr = string
    az   = string
    name = string
  }))
}

variable "nat_gateway_enabled" {
  description = "Enable NAT Gateway for private subnets"
  type        = bool
  default     = true
}

variable "nat_gateway_ha" {
  description = "Enable high availability NAT Gateway (one per AZ)"
  type        = bool
  default     = true
}

variable "flow_logs_enabled" {
  description = "Enable VPC Flow Logs"
  type        = bool
  default     = true
}

variable "flow_logs_retention_days" {
  description = "Retention period for VPC Flow Logs in days"
  type        = number
  default     = 90
}

variable "vpc_endpoints_enabled" {
  description = "Enable VPC endpoints for AWS services"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

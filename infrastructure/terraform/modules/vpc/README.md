# VPC Module

This Terraform module creates a VPC with multi-tier networking for the Multi-Region GPU Cluster.

## Features

- Multi-AZ VPC with public, private, FSx, and Transit Gateway subnets
- NAT Gateways with optional high availability (one per AZ)
- VPC Flow Logs with CloudWatch integration
- VPC Endpoints for AWS services (S3, DynamoDB, KMS, EC2, CloudWatch)
- Internet Gateway for public subnets
- Proper route tables for each subnet type

## Usage

```hcl
module "vpc" {
  source = "../../modules/vpc"

  name_prefix = "mrgc-use1"
  region      = "us-east-1"
  vpc_cidr    = "10.66.0.0/18"

  public_subnets = [
    { cidr = "10.66.0.0/24", az = "us-east-1a", name = "public-use1a" },
    { cidr = "10.66.1.0/24", az = "us-east-1b", name = "public-use1b" },
    { cidr = "10.66.2.0/24", az = "us-east-1c", name = "public-use1c" }
  ]

  private_subnets = [
    { cidr = "10.66.10.0/23", az = "us-east-1a", name = "private-use1a" },
    { cidr = "10.66.12.0/23", az = "us-east-1b", name = "private-use1b" },
    { cidr = "10.66.14.0/23", az = "us-east-1c", name = "private-use1c" }
  ]

  fsx_subnets = [
    { cidr = "10.66.20.0/24", az = "us-east-1a", name = "fsx-use1a" },
    { cidr = "10.66.21.0/24", az = "us-east-1b", name = "fsx-use1b" }
  ]

  tgw_subnets = [
    { cidr = "10.66.30.0/28", az = "us-east-1a", name = "tgw-use1a" },
    { cidr = "10.66.30.16/28", az = "us-east-1b", name = "tgw-use1b" }
  ]

  nat_gateway_enabled = true
  nat_gateway_ha      = true
  flow_logs_enabled   = true
  vpc_endpoints_enabled = true

  tags = {
    Project     = "MRGC"
    Environment = "production"
  }
}
```

## Subnet Architecture

### Public Subnets
- Used for NLBs, NAT Gateways, and bastion hosts
- Route: 0.0.0.0/0 → Internet Gateway

### Private Subnets
- Used for GPU instances (g6e.2xlarge with Nitro Enclaves)
- Route: 0.0.0.0/0 → NAT Gateway (for outbound internet access)
- Cross-region routes added via Transit Gateway

### FSx Subnets
- Used for FSx Lustre file systems
- Isolated from internet
- Cross-region routes via Transit Gateway

### Transit Gateway Subnets
- Small subnets for TGW attachments
- Used only for cross-region routing

## VPC Endpoints

The module creates VPC endpoints to access AWS services privately:

- **S3** (Gateway): Fast model uploads/downloads
- **DynamoDB** (Gateway): Global state management
- **KMS** (Interface): Encryption key management for Nitro Enclaves
- **EC2** (Interface): Instance management
- **CloudWatch Logs/Monitoring** (Interface): Observability

## Inputs

See [variables.tf](./variables.tf) for full list of inputs.

## Outputs

See [outputs.tf](./outputs.tf) for full list of outputs.

## Network Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         VPC (10.66.x.0/18)                  │
│                                                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Public Subnets (3 AZs)                             │   │
│  │ - NLBs for Global Accelerator                      │   │
│  │ - NAT Gateways (HA)                                │   │
│  │ - Internet Gateway                                 │   │
│  └────────────────────────────────────────────────────┘   │
│                            ↓                               │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Private Subnets (3 AZs)                            │   │
│  │ - GPU Instances (g6e.2xlarge)                      │   │
│  │ - Nitro Enclaves                                   │   │
│  │ - Regional Routers (ECS Fargate)                   │   │
│  │ - VPC Endpoints (KMS, EC2, CloudWatch)             │   │
│  └────────────────────────────────────────────────────┘   │
│                            ↓                               │
│  ┌────────────────────────────────────────────────────┐   │
│  │ FSx Subnets (2 AZs)                                │   │
│  │ - FSx Lustre (2.4TB, 800 MB/s)                     │   │
│  └────────────────────────────────────────────────────┘   │
│                            ↓                               │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Transit Gateway Subnets (2 AZs)                    │   │
│  │ - TGW Attachments                                  │   │
│  │ - Cross-region routing                             │   │
│  └────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ↓
                     Transit Gateway
                            ↓
              ┌─────────────┴─────────────┐
              ↓                           ↓
         us-east-2 VPC              us-west-2 VPC
```

## High Availability

- **Multi-AZ**: All subnets span multiple availability zones
- **NAT Gateway HA**: One NAT Gateway per AZ (optional, can use single for cost savings)
- **VPC Endpoints**: Interface endpoints span all AZs
- **FSx Lustre**: Multi-AZ deployment for high availability

## Security

- **Flow Logs**: All traffic logged to CloudWatch (90-day retention)
- **Private Endpoints**: VPC endpoints eliminate internet traversal for AWS services
- **Isolation**: Separate subnets for different workload types
- **No public IPs**: GPU instances and FSx have no public IP addresses

## Cost Optimization

- Use single NAT Gateway (set `nat_gateway_ha = false`) for dev/staging
- VPC endpoints reduce data transfer costs vs NAT Gateway
- Flow logs can be disabled in dev environments

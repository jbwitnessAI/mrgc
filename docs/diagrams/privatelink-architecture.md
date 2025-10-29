# PrivateLink Architecture

## Overview

AWS PrivateLink provides private connectivity between tenant VPCs and the Multi-Region GPU Cluster without traffic traversing the public internet.

## Full Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                     Tenant VPC (10.34.0.0/16)                  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Application Servers                                      │ │
│  │ - Send encrypted requests to GPU cluster                │ │
│  │ - Use private IPs: 10.34.10.50, 10.34.11.50            │ │
│  └───────────────────────┬──────────────────────────────────┘ │
│                          │                                     │
│                          ↓                                     │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ VPC Endpoint (Interface Endpoint)                        │ │
│  │                                                           │ │
│  │ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │ │
│  │ │ Subnet A    │  │ Subnet B    │  │ Subnet C    │      │ │
│  │ │ AZ: use1a   │  │ AZ: use1b   │  │ AZ: use1c   │      │ │
│  │ │ ENI:        │  │ ENI:        │  │ ENI:        │      │ │
│  │ │ 10.34.10.50 │  │ 10.34.11.50 │  │ 10.34.12.50 │      │ │
│  │ └─────────────┘  └─────────────┘  └─────────────┘      │ │
│  └──────────────────────┬───────────────────────────────────┘ │
└─────────────────────────┼──────────────────────────────────────┘
                          │
                          │ AWS PrivateLink
                          │ (Private AWS Network)
                          │
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│              GPU Cluster VPC (10.66.0.0/18)                     │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ VPC Endpoint Service                                       │ │
│  │ Service Name: com.amazonaws.vpce.us-east-1.vpce-svc-xxx   │ │
│  │                                                            │ │
│  │ Connected to: Network Load Balancer                       │ │
│  └────────────────────────┬───────────────────────────────────┘ │
│                           │                                      │
│                           ↓                                      │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Network Load Balancer (mrgc-nlb-use1)                     │ │
│  │                                                            │ │
│  │ ┌────────────┐  ┌────────────┐  ┌────────────┐          │ │
│  │ │ AZ: use1a  │  │ AZ: use1b  │  │ AZ: use1c  │          │ │
│  │ │ Listener:  │  │ Listener:  │  │ Listener:  │          │ │
│  │ │ 443, 8080  │  │ 443, 8080  │  │ 443, 8080  │          │ │
│  │ └────────────┘  └────────────┘  └────────────┘          │ │
│  └────────────────────────┬───────────────────────────────────┘ │
│                           │                                      │
│                           ↓                                      │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Regional Router (ECS Fargate)                             │ │
│  │ - Receives request via NLB                                │ │
│  │ - Selects best GPU instance                               │ │
│  │ - Forwards encrypted request                              │ │
│  └────────────────────────┬───────────────────────────────────┘ │
│                           │                                      │
│                           ↓                                      │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ GPU Instances (g6e.2xlarge with Nitro Enclaves)          │ │
│  │ - Decrypt request in Nitro Enclave                        │ │
│  │ - Run inference on GPU                                     │ │
│  │ - Encrypt response                                         │ │
│  └────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## Request Flow with PrivateLink

```
Step 1: Tenant Application Encrypts Request
┌─────────────────────────┐
│ Tenant App              │
│ - Encrypt with KMS      │
│ - Target: 10.34.10.50   │
└───────────┬─────────────┘
            │
            ↓
Step 2: Traffic Routes to VPC Endpoint ENI
┌─────────────────────────┐
│ VPC Endpoint ENI        │
│ - Private IP            │
│ - In tenant's subnet    │
└───────────┬─────────────┘
            │
            │ AWS PrivateLink (Private Network)
            │ - No internet traversal
            │ - Uses AWS backbone
            │
            ↓
Step 3: NLB Receives Connection
┌─────────────────────────┐
│ Network Load Balancer   │
│ - Port 443              │
│ - Health checks enabled │
└───────────┬─────────────┘
            │
            ↓
Step 4: Regional Router Routes to GPU
┌─────────────────────────┐
│ Regional Router         │
│ - Select best GPU       │
│ - Forward request       │
└───────────┬─────────────┘
            │
            ↓
Step 5: Nitro Enclave Decrypts
┌─────────────────────────┐
│ GPU Instance            │
│ - Nitro: Decrypt        │
│ - Parent: Inference     │
│ - Nitro: Encrypt        │
└───────────┬─────────────┘
            │
            ↓
Step 6: Response Returns via Same Path
┌─────────────────────────┐
│ Tenant App              │
│ - Receive encrypted     │
│ - Decrypt with KMS      │
└─────────────────────────┘
```

## Connectivity Options Comparison

### Option 1: Public Internet (Without PrivateLink)

```
Tenant App → Internet Gateway → Public Internet
    ↓
AWS Global Accelerator (Public IPs: 75.2.x.x)
    ↓
NLB → Regional Router → GPU Instances

Latency: 160-180ms (P95)
Security: Encrypted, but traverses internet
Cost: $0 (Global Accelerator included)
Compliance: Not suitable for HIPAA/PCI-DSS
```

### Option 2: PrivateLink (Recommended)

```
Tenant App → VPC Endpoint (Private IPs: 10.34.10.x)
    ↓
AWS PrivateLink (Private AWS Network)
    ↓
NLB → Regional Router → GPU Instances

Latency: 140-160ms (P95) - 5-10ms faster
Security: Never leaves AWS network
Cost: ~$22/month per region
Compliance: Suitable for HIPAA/PCI-DSS
```

### Option 3: PrivateLink + Global Accelerator

```
Tenant App → VPC Endpoint → PrivateLink
    ↓
AWS Global Accelerator (Private)
    ↓
NLB → Regional Router → GPU Instances

Latency: 145-165ms (P95)
Security: Private + automatic failover
Cost: ~$22/month + $18/month = $40/month
Use case: Best of both worlds
```

## Multi-Region PrivateLink Setup

### Scenario 1: Tenant in All 3 Regions

```
┌────────────────────────────────────────────────────────────┐
│ Tenant us-east-1 VPC                                       │
│   VPC Endpoint → PrivateLink → us-east-1 GPU Cluster      │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ Tenant us-east-2 VPC                                       │
│   VPC Endpoint → PrivateLink → us-east-2 GPU Cluster      │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ Tenant us-west-2 VPC                                       │
│   VPC Endpoint → PrivateLink → us-west-2 GPU Cluster      │
└────────────────────────────────────────────────────────────┘

Cost: $64.80/month (3 regions × $21.60)
Benefit: Lowest latency everywhere
```

### Scenario 2: Tenant in One Region with Failover

```
┌────────────────────────────────────────────────────────────┐
│ Tenant us-east-1 VPC                                       │
│                                                            │
│   Primary:                                                 │
│   VPC Endpoint → PrivateLink → us-east-1 GPU Cluster      │
│                                                            │
│   Failover (via Transit Gateway):                         │
│   Transit Gateway → us-east-2 VPC → PrivateLink           │
│                                  → us-east-2 GPU Cluster   │
└────────────────────────────────────────────────────────────┘

Cost: $21.60/month + TGW costs
Benefit: DR capability, higher latency on failover
```

## VPC Endpoint Connection Lifecycle

```
┌─────────────────────┐
│ Tenant Creates      │
│ VPC Endpoint        │
└──────────┬──────────┘
           │
           ↓
┌──────────────────────────────────────┐
│ State: pendingAcceptance             │
│ - Waits for approval                 │
│ - Can take up to 4 hours             │
└──────────┬───────────────────────────┘
           │
           ↓
┌──────────────────────────────────────┐
│ GPU Cluster Team Approves            │
│ - Manual or automated                │
│ - Validates tenant account           │
└──────────┬───────────────────────────┘
           │
           ↓
┌──────────────────────────────────────┐
│ State: available                     │
│ - ENIs created in tenant subnets     │
│ - Private IPs assigned               │
│ - Ready for traffic                  │
└──────────┬───────────────────────────┘
           │
           ↓
┌──────────────────────────────────────┐
│ Tenant Tests Connectivity            │
│ - curl http://{private-ip}:8080/health
│ - Verify 200 OK response             │
└──────────┬───────────────────────────┘
           │
           ↓
┌──────────────────────────────────────┐
│ Production Traffic                   │
│ - Update app to use private IPs      │
│ - Monitor latency and errors         │
└──────────────────────────────────────┘
```

## Security Architecture

```
┌────────────────────────────────────────────────────────────┐
│ Tenant VPC                                                 │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ Security Group (Outbound Rules)                      │ │
│  │ - TCP 443 to 0.0.0.0/0 (HTTPS inference)            │ │
│  │ - TCP 8080 to 0.0.0.0/0 (HTTP health)               │ │
│  └──────────────────────────────────────────────────────┘ │
│                          ↓                                 │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ VPC Endpoint Policy (Optional)                       │ │
│  │ - Restrict to specific principals                    │ │
│  │ - Limit to specific actions                          │ │
│  └──────────────────────────────────────────────────────┘ │
└─────────────────────────┬──────────────────────────────────┘
                          │
                          │ PrivateLink (Encrypted in transit)
                          │
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ GPU Cluster VPC                                             │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ VPC Endpoint Service                                 │  │
│  │ - Acceptance required: true                          │  │
│  │ - Allowed principals: [tenant accounts]              │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ↓                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ NLB Security Group                                   │  │
│  │ - Inbound: TCP 443, 8080 from VPC CIDR              │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Latency Breakdown

### Without PrivateLink (Public Internet)
```
Tenant App → Internet: 20-30ms
Internet → Global Accelerator: 10-20ms
Global Accelerator → NLB: 5-10ms
NLB → Regional Router: 2-5ms
Regional Router → GPU: 1-2ms
GPU Processing: 100-500ms
Return Path: 38-67ms

Total: 176-634ms (P95: ~600ms)
```

### With PrivateLink
```
Tenant App → VPC Endpoint: 1-2ms
VPC Endpoint → PrivateLink: 2-5ms
PrivateLink → NLB: 2-5ms
NLB → Regional Router: 2-5ms
Regional Router → GPU: 1-2ms
GPU Processing: 100-500ms
Return Path: 8-19ms

Total: 116-538ms (P95: ~520ms)
```

**Improvement**: ~80ms faster (P95)

## Cost Analysis

### Single Region Setup

| Component | Cost | Notes |
|-----------|------|-------|
| VPC Endpoint (3 AZs) | $21.60/month | $0.01/hour × 24 × 30 × 3 |
| Data Transfer | $0.01/GB | Much cheaper than internet |
| Example (1TB/month) | $10/month | 1000 GB × $0.01 |
| **Total** | **$31.60/month** | Per region |

### Multi-Region Setup (3 Regions)

| Component | Cost | Notes |
|-----------|------|-------|
| VPC Endpoints (3 regions) | $64.80/month | $21.60 × 3 |
| Data Transfer | ~$30/month | 1TB × 3 regions |
| **Total** | **$94.80/month** | All regions |

### Cost Comparison

| Connectivity Method | Setup Cost | Monthly Cost | Data Transfer |
|---------------------|------------|--------------|---------------|
| Public Internet | $0 | $0 | $0.09/GB out |
| PrivateLink (1 region) | $0 | $21.60 | $0.01/GB |
| PrivateLink (3 regions) | $0 | $64.80 | $0.01/GB |
| PrivateLink + GA | $0 | $82.80 | $0.01/GB |

**Breakeven**: At ~300 GB/month, PrivateLink becomes cheaper than public internet

## Monitoring and Observability

### Tenant-Side Metrics

```
aws cloudwatch get-metric-data \
  --namespace AWS/PrivateLinkEndpoints \
  --metric-name BytesProcessed \
  --dimensions Name=VpcEndpointId,Value=vpce-xxx \
  --start-time 2025-01-28T00:00:00Z \
  --end-time 2025-01-28T23:59:59Z \
  --period 3600 \
  --statistics Sum
```

### GPU Cluster-Side Metrics

```
aws cloudwatch get-metric-data \
  --namespace AWS/PrivateLinkServices \
  --metric-name ActiveConnections \
  --dimensions Name=ServiceId,Value=vpce-svc-xxx \
  --start-time 2025-01-28T00:00:00Z \
  --end-time 2025-01-28T23:59:59Z \
  --period 3600 \
  --statistics Average
```

## High Availability

### VPC Endpoint HA

```
VPC Endpoint with 3 ENIs (one per AZ)
├── ENI in us-east-1a (10.34.10.50) ✅
├── ENI in us-east-1b (10.34.11.50) ✅
└── ENI in us-east-1c (10.34.12.50) ✅

If one AZ fails:
- Traffic automatically routes to healthy ENIs
- No configuration changes needed
- < 30 second failover
```

### NLB HA

```
NLB spans 3 AZs
├── AZ-a: Healthy targets ✅
├── AZ-b: Healthy targets ✅
└── AZ-c: Healthy targets ✅

If one AZ fails:
- Cross-zone load balancing active
- Traffic routes to healthy AZs
- No impact to tenants
```

## Best Practices

1. **Always use 3 subnets** (one per AZ) for VPC endpoints
2. **Enable private DNS** for easier management
3. **Test failover** by disabling one subnet temporarily
4. **Monitor latency** and compare to baseline
5. **Use VPC endpoint policy** to restrict access
6. **Tag resources** for cost tracking
7. **Set up CloudWatch alarms** for connection issues
8. **Document private IPs** in your configuration management
9. **Test DR** by connecting through different regions
10. **Review security groups** quarterly

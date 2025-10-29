# Cross-Region Networking Architecture

## Overview

The Multi-Region GPU Cluster uses AWS Transit Gateway with cross-region peering to create a single logical network spanning 3 AWS regions. This enables GPU instances and FSx Lustre storage to communicate privately across regions.

## Network Topology

```
                    ┌─────────────────────────────────┐
                    │   Tenant VPCs (Customer Side)   │
                    │     10.34.x.0/16 (example)      │
                    └────────────┬────────────────────┘
                                 │
                                 │ PrivateLink
                                 ↓
        ┌────────────────────────────────────────────────────┐
        │       AWS Global Accelerator (Anycast IPs)        │
        │           static-ip-1.amazonaws.com                │
        │           static-ip-2.amazonaws.com                │
        └─────────┬──────────────┬──────────────┬───────────┘
                  │              │              │
       ┌──────────┴─────┐ ┌──────┴──────┐ ┌────┴──────────┐
       │   us-east-1    │ │  us-east-2  │ │   us-west-2   │
       │                │ │             │ │               │
       │  Regional NLB  │ │ Regional NLB│ │ Regional NLB  │
       └──────┬─────────┘ └──────┬──────┘ └───────┬───────┘
              │                  │                 │
              ↓                  ↓                 ↓
    ┌──────────────────┐ ┌──────────────┐ ┌──────────────┐
    │ VPC 10.66.0.0/18 │ │ VPC 10.66.   │ │ VPC 10.66.   │
    │                  │ │ 64.0/18      │ │ 128.0/18     │
    │  ┌────────────┐  │ │ ┌──────────┐ │ │ ┌──────────┐ │
    │  │ Public /24 │  │ │ │Public /24│ │ │ │Public /24│ │
    │  └──────┬─────┘  │ │ └────┬─────┘ │ │ └────┬─────┘ │
    │         │        │ │      │       │ │      │       │
    │  ┌──────┴──────┐ │ │ ┌────┴──────┐│ │ ┌────┴──────┐│
    │  │Private /23  │ │ │ │Private/23 ││ │ │Private/23 ││
    │  │  GPU        │ │ │ │  GPU      ││ │ │  GPU      ││
    │  │  Instances  │ │ │ │  Instances││ │ │  Instances││
    │  └──────┬──────┘ │ │ └────┬──────┘│ │ └────┬──────┘│
    │         │        │ │      │       │ │      │       │
    │  ┌──────┴──────┐ │ │ ┌────┴──────┐│ │ ┌────┴──────┐│
    │  │FSx /24      │ │ │ │FSx /24    ││ │ │FSx /24    ││
    │  │Lustre       │ │ │ │Lustre     ││ │ │Lustre     ││
    │  └──────┬──────┘ │ │ └────┬──────┘│ │ └────┬──────┘│
    │         │        │ │      │       │ │      │       │
    │  ┌──────┴──────┐ │ │ ┌────┴──────┐│ │ ┌────┴──────┐│
    │  │TGW /28      │ │ │ │TGW /28    ││ │ │TGW /28    ││
    │  │Attachment   │ │ │ │Attachment ││ │ │Attachment ││
    │  └──────┬──────┘ │ │ └────┬──────┘│ │ └────┬──────┘│
    └─────────┼────────┘ └──────┼───────┘ └───────┼───────┘
              │                 │                  │
              ↓                 ↓                  ↓
       ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
       │ Transit      │  │ Transit      │  │ Transit      │
       │ Gateway      │  │ Gateway      │  │ Gateway      │
       │ us-east-1    │  │ us-east-2    │  │ us-west-2    │
       │ ASN: 64512   │  │ ASN: 64512   │  │ ASN: 64512   │
       └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
              │                 │                  │
              └────────┬────────┴─────────┬────────┘
                       │                  │
                   ┌───┴────┐      ┌──────┴────┐
                   │ Peering│      │  Peering  │
                   │ use1   │      │  use1     │
                   │ ↔      │      │  ↔        │
                   │ use2   │      │  usw2     │
                   └────────┘      └───────────┘

                          ┌────────────┐
                          │  Peering   │
                          │  use2      │
                          │  ↔         │
                          │  usw2      │
                          └────────────┘
```

## Network CIDR Allocation

### Base Network: 10.66.0.0/16

| Region    | VPC CIDR       | Public Subnets | Private Subnets | FSx Subnets  | TGW Subnets    |
|-----------|----------------|----------------|-----------------|--------------|----------------|
| us-east-1 | 10.66.0.0/18   | 10.66.0.0/24   | 10.66.10.0/23   | 10.66.20.0/24| 10.66.30.0/28  |
|           |                | 10.66.1.0/24   | 10.66.12.0/23   | 10.66.21.0/24| 10.66.30.16/28 |
|           |                | 10.66.2.0/24   | 10.66.14.0/23   |              |                |
| us-east-2 | 10.66.64.0/18  | 10.66.64.0/24  | 10.66.74.0/23   | 10.66.84.0/24| 10.66.94.0/28  |
|           |                | 10.66.65.0/24  | 10.66.76.0/23   | 10.66.85.0/24| 10.66.94.16/28 |
|           |                | 10.66.66.0/24  | 10.66.78.0/23   |              |                |
| us-west-2 | 10.66.128.0/18 | 10.66.128.0/24 | 10.66.138.0/23  | 10.66.148.0/24| 10.66.158.0/28|
|           |                | 10.66.129.0/24 | 10.66.140.0/23  | 10.66.149.0/24| 10.66.158.16/28|
|           |                | 10.66.130.0/24 | 10.66.142.0/23  |              |                |

## Traffic Flow Patterns

### 1. Intra-Region Request Flow

```
Tenant VPC → Global Accelerator → Regional NLB → Regional Router (ECS)
    ↓
GPU Instance in same region
    ↓
FSx Lustre in same region
    ↓
Response back to tenant
```

**Latency**: ~10-20ms total

### 2. Cross-Region Failover Flow

```
Tenant VPC (us-east-1) → Global Accelerator → Health Check Fails
    ↓
Automatic route to us-east-2 Regional NLB
    ↓
Transit Gateway Peering (use1 → use2)
    ↓
GPU Instance in us-east-2
    ↓
FSx Lustre in us-east-2
    ↓
Response via Transit Gateway back to us-east-1 NLB → Tenant
```

**Latency**: ~30-50ms additional (cross-region TGW adds ~15ms)

### 3. GPU-to-FSx Communication

All GPU instances access their **local region's FSx Lustre** for model loading:

```
GPU Instance (10.66.10.0/23) → FSx Subnet (10.66.20.0/24)
    ↓
FSx Lustre file system
    ↓
Model loaded via memory-mapped I/O (30-45 seconds for 26GB model)
```

**Throughput**: 800 MB/s per FSx file system

### 4. Global State Synchronization

```
GPU Instance → VPC Endpoint (DynamoDB) → DynamoDB Global Table
    ↑                                              ↓
    └──────── Replication < 1 second ──────────────┘
         (across all 3 regions)
```

## Transit Gateway Peering

### Peering Connections

1. **us-east-1 ↔ us-east-2**
   - Latency: ~15-20ms
   - Bandwidth: Up to 50 Gbps
   - Use case: Primary DR path

2. **us-east-1 ↔ us-west-2**
   - Latency: ~65-80ms
   - Bandwidth: Up to 50 Gbps
   - Use case: West coast failover

3. **us-east-2 ↔ us-west-2**
   - Latency: ~50-65ms
   - Bandwidth: Up to 50 Gbps
   - Use case: East-West failover

### Route Propagation

Each Transit Gateway has routes to all other regions:

**us-east-1 TGW Routes:**
```
10.66.0.0/18   → local (VPC attachment)
10.66.64.0/18  → TGW Peering to us-east-2
10.66.128.0/18 → TGW Peering to us-west-2
```

**us-east-2 TGW Routes:**
```
10.66.0.0/18   → TGW Peering to us-east-1
10.66.64.0/18  → local (VPC attachment)
10.66.128.0/18 → TGW Peering to us-west-2
```

**us-west-2 TGW Routes:**
```
10.66.0.0/18   → TGW Peering to us-east-1
10.66.64.0/18  → TGW Peering to us-east-2
10.66.128.0/18 → local (VPC attachment)
```

## Security Groups

### GPU Instance Security Group

**Inbound:**
- Port 8080 (HTTP API) from Regional Router SG
- Port 443 (HTTPS) from Regional Router SG
- ALL ICMP from 10.66.0.0/16 (ping/troubleshooting)

**Outbound:**
- Port 443 to VPC Endpoints (KMS, DynamoDB, CloudWatch)
- Port 988 to FSx Lustre
- ALL traffic to 10.66.0.0/16 (cross-region communication)

### FSx Lustre Security Group

**Inbound:**
- Port 988 (Lustre) from GPU Instance SG
- Port 1021-1023 (Lustre) from GPU Instance SG

**Outbound:**
- ALL traffic to 10.66.0.0/16

### Regional Router Security Group

**Inbound:**
- Port 443 from NLB
- Port 8080 from NLB

**Outbound:**
- Port 8080/443 to GPU Instance SG
- Port 443 to VPC Endpoints (DynamoDB, CloudWatch)

## Bandwidth and Cost

### Inter-Region Data Transfer Costs

| Route          | Cost per GB  | Expected Monthly | Cost/Month |
|----------------|--------------|------------------|------------|
| use1 ↔ use2    | $0.01        | 500 GB          | $5         |
| use1 ↔ usw2    | $0.02        | 100 GB          | $2         |
| use2 ↔ usw2    | $0.02        | 100 GB          | $2         |
| **Total**      |              |                 | **$9/month** |

*Inter-region data transfer is minimal because tenants primarily use their nearest region*

### Transit Gateway Costs

| Component              | Cost          | Quantity | Monthly Cost |
|------------------------|---------------|----------|--------------|
| TGW Attachment         | $0.05/hour    | 3        | $108         |
| TGW Data Processing    | $0.02/GB      | 700 GB   | $14          |
| TGW Peering Attachment | $0.05/hour    | 3        | $108         |
| **Total TGW**          |               |          | **$230/month** |

## High Availability Design

### Regional Failure Scenarios

**Scenario 1: us-east-1 Complete Failure**
```
Before:
- use1: 17 GPUs, use2: 17 GPUs, usw2: 16 GPUs
- Total: 50 GPUs

After:
- use1: 0 GPUs (FAILED)
- use2: 17 GPUs + auto-scale to 25 GPUs
- usw2: 16 GPUs + auto-scale to 25 GPUs
- Total: 50 GPUs maintained

Traffic automatically routes via Global Accelerator to use2/usw2
```

**Recovery Time**: < 60 seconds (Global Accelerator health check + auto-scaling)

**Scenario 2: Transit Gateway Peering Failure**
```
If use1 ↔ use2 peering fails:
- Local traffic unaffected
- Cross-region requests route via use1 ↔ usw2 ↔ use2
- Latency increase: +30-50ms
- Automatic BGP rerouting
```

## Monitoring

### Key Metrics

1. **Transit Gateway Metrics**
   - `BytesIn` / `BytesOut` - Cross-region traffic
   - `PacketDropCountBlackhole` - Routing issues
   - `BytesDropCountBlackhole` - Bandwidth issues

2. **VPC Flow Logs**
   - Cross-region connection patterns
   - Security group violations
   - Network troubleshooting

3. **Latency Metrics**
   - Regional Router → GPU Instance: < 5ms
   - Cross-region TGW latency: 15-80ms
   - End-to-end tenant latency: P95 < 2 seconds

## Deployment Steps

1. **Create VPCs in all 3 regions** (Terraform module: `vpc`)
2. **Deploy Transit Gateways** (Terraform module: `transit-gateway`)
3. **Create TGW Peering** (Terraform root module with multi-region providers)
4. **Configure route tables** (automatic via TGW module)
5. **Deploy VPC endpoints** (automatic via VPC module)
6. **Configure security groups** (application-specific)
7. **Test connectivity** (ping, iperf3 across regions)

## Testing Cross-Region Connectivity

```bash
# From GPU instance in us-east-1, test connectivity to us-east-2
ping 10.66.74.10  # GPU instance in use2

# Test FSx Lustre access across regions (for DR scenarios)
mount -t lustre 10.66.84.50@tcp:/fsx /mnt/fsx-use2

# Test latency
ping -c 100 10.66.74.10 | tail -1

# Expected: avg ~15-20ms for use1 ↔ use2
```

## Security Considerations

1. **No Internet Transit**: All cross-region traffic uses AWS private network via Transit Gateway
2. **Encryption**: All TGW traffic encrypted by default (IPsec not needed)
3. **Isolation**: Each tenant's data encrypted with their own KMS keys
4. **Network ACLs**: Default allow within 10.66.0.0/16, deny all else
5. **Flow Logs**: 90-day retention for compliance and forensics

## Future Expansion

To add a 4th region (e.g., eu-west-1):

1. Allocate CIDR: `10.66.192.0/18`
2. Deploy VPC + TGW in eu-west-1
3. Create 3 peering connections (to use1, use2, usw2)
4. Update Global Accelerator endpoint group
5. Update route tables in all regions
6. Deploy FSx Lustre in eu-west-1

**Estimated Time**: 1 week

# PrivateLink Setup Guide for Tenants

## Overview

AWS PrivateLink allows you to connect to the Multi-Region GPU Cluster privately from your VPC without traversing the public internet. This provides:

- **Lower latency**: 5-10ms faster than public internet
- **Better security**: Traffic never leaves AWS network
- **Compliance**: Required for HIPAA, PCI-DSS workloads
- **Higher reliability**: 99.99% SLA

## Architecture

```
Your VPC (10.34.0.0/16)
    │
    ├── Private Subnet A (10.34.10.0/24)
    │   └── VPC Endpoint ENI (10.34.10.50)
    │
    ├── Private Subnet B (10.34.11.0/24)
    │   └── VPC Endpoint ENI (10.34.11.50)
    │
    └── Private Subnet C (10.34.12.0/24)
        └── VPC Endpoint ENI (10.34.12.50)
                │
                ↓ (AWS PrivateLink - Private Network)
                │
        ┌───────┴────────┐
        │                │
   NLB (us-east-1)  NLB (us-east-2)  NLB (us-west-2)
        │                │                │
Regional Router    Regional Router   Regional Router
        │                │                │
   GPU Instances   GPU Instances    GPU Instances
```

## Prerequisites

1. **AWS Account** with VPC
2. **Private subnets** (at least 2, recommended 3 for HA)
3. **Service name** from GPU cluster team
4. **Approval** from GPU cluster team for your AWS account

## Step 1: Get Service Name

Contact the GPU cluster team to get:
- VPC Endpoint Service Name (per region)
- Your AWS account approved

**Example service names:**
```
us-east-1: com.amazonaws.vpce.us-east-1.vpce-svc-0123456789abcdef0
us-east-2: com.amazonaws.vpce.us-east-2.vpce-svc-0fedcba9876543210
us-west-2: com.amazonaws.vpce.us-west-2.vpce-svc-0a1b2c3d4e5f67890
```

## Step 2: Create VPC Endpoint

### Via AWS Console

1. Navigate to **VPC Console** → **Endpoints**
2. Click **Create Endpoint**
3. Configure:
   - **Service category**: Other endpoint services
   - **Service name**: Paste the service name (e.g., `com.amazonaws.vpce.us-east-1.vpce-svc-0123456789abcdef0`)
   - Click **Verify service**
4. Select your **VPC**
5. Select **Subnets** (recommended: 3 subnets in different AZs)
6. Select **Security Group** (must allow outbound TCP 443 and 8080)
7. Click **Create endpoint**

### Via AWS CLI

```bash
# Create VPC endpoint
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-12345678 \
  --vpc-endpoint-type Interface \
  --service-name com.amazonaws.vpce.us-east-1.vpce-svc-0123456789abcdef0 \
  --subnet-ids subnet-aaa subnet-bbb subnet-ccc \
  --security-group-ids sg-xyz \
  --region us-east-1

# Output:
{
  "VpcEndpoint": {
    "VpcEndpointId": "vpce-0abcd1234efgh5678",
    "State": "pendingAcceptance",
    "ServiceName": "com.amazonaws.vpce.us-east-1.vpce-svc-0123456789abcdef0",
    ...
  }
}
```

### Via Terraform

```hcl
resource "aws_vpc_endpoint" "gpu_cluster" {
  vpc_id             = aws_vpc.main.id
  service_name       = "com.amazonaws.vpce.us-east-1.vpce-svc-0123456789abcdef0"
  vpc_endpoint_type  = "Interface"
  subnet_ids         = [
    aws_subnet.private_a.id,
    aws_subnet.private_b.id,
    aws_subnet.private_c.id
  ]
  security_group_ids = [aws_security_group.gpu_cluster_client.id]

  private_dns_enabled = true

  tags = {
    Name = "gpu-cluster-privatelink"
  }
}

resource "aws_security_group" "gpu_cluster_client" {
  name_prefix = "gpu-cluster-client-"
  vpc_id      = aws_vpc.main.id

  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS to GPU cluster"
  }

  egress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP health checks"
  }
}

output "endpoint_private_ips" {
  value = aws_vpc_endpoint.gpu_cluster.network_interface_ids
}
```

## Step 3: Wait for Approval

After creating the VPC endpoint:

1. **Status**: `pendingAcceptance`
2. **Wait time**: Up to 4 hours (typically < 1 hour)
3. **Notification**: GPU cluster team will notify you when approved
4. **New status**: `available`

Check status:
```bash
aws ec2 describe-vpc-endpoints \
  --vpc-endpoint-ids vpce-0abcd1234efgh5678 \
  --query 'VpcEndpoints[0].State'

# Output: "available"
```

## Step 4: Get Private IP Addresses

Once approved, get the private IPs:

```bash
# Get ENI IDs
aws ec2 describe-vpc-endpoints \
  --vpc-endpoint-ids vpce-0abcd1234efgh5678 \
  --query 'VpcEndpoints[0].NetworkInterfaceIds' \
  --output text

# Get private IPs from ENIs
aws ec2 describe-network-interfaces \
  --network-interface-ids eni-aaa eni-bbb eni-ccc \
  --query 'NetworkInterfaces[*].PrivateIpAddress' \
  --output text

# Example output:
10.34.10.50 10.34.11.50 10.34.12.50
```

## Step 5: Test Connectivity

### Test with curl

```bash
# Test health endpoint (HTTP)
curl -v http://10.34.10.50:8080/health

# Expected response:
{
  "status": "healthy",
  "region": "us-east-1",
  "available_capacity": 45,
  "timestamp": 1699564800
}
```

### Test with Python

```python
import requests

# Private IPs from your VPC endpoint
PRIVATE_IPS = ["10.34.10.50", "10.34.11.50", "10.34.12.50"]

# Test health endpoint
for ip in PRIVATE_IPS:
    try:
        response = requests.get(
            f"http://{ip}:8080/health",
            timeout=5
        )
        print(f"{ip}: {response.status_code} - {response.json()['status']}")
    except Exception as e:
        print(f"{ip}: FAILED - {e}")

# Expected output:
# 10.34.10.50: 200 - healthy
# 10.34.11.50: 200 - healthy
# 10.34.12.50: 200 - healthy
```

## Step 6: Update Your Application

### Option 1: Use VPC Endpoint DNS (Recommended)

If `private_dns_enabled = true`, use the endpoint DNS name:

```python
import boto3
import requests
import json

# VPC Endpoint DNS automatically resolves to private IPs
ENDPOINT = "gpu-cluster.yourcompany.internal"  # Or use endpoint DNS

# Your inference request
kms = boto3.client('kms', region_name='us-east-1')
payload = {"prompt": "Hello", "max_tokens": 50}

encrypted = kms.encrypt(
    KeyId='your-kms-key-arn',
    Plaintext=json.dumps(payload).encode()
)['CiphertextBlob']

# Send via PrivateLink
response = requests.post(
    f'https://{ENDPOINT}:443/inference',
    headers={
        'Content-Type': 'application/octet-stream',
        'X-Tenant-ID': 'your-tenant-id',
        'X-KMS-Key-ID': 'your-kms-key-arn',
        'X-Model-Pool': 'model-a'
    },
    data=encrypted,
    timeout=30
)
```

### Option 2: Use Private IPs Directly

```python
# Use private IPs with round-robin or random selection
PRIVATE_IPS = ["10.34.10.50", "10.34.11.50", "10.34.12.50"]

import random
selected_ip = random.choice(PRIVATE_IPs)

response = requests.post(
    f'https://{selected_ip}:443/inference',
    headers={...},
    data=encrypted
)
```

## Security Group Configuration

Your security group must allow:

### Outbound Rules

| Type | Protocol | Port | Destination | Description |
|------|----------|------|-------------|-------------|
| HTTPS | TCP | 443 | 0.0.0.0/0 | Inference requests |
| HTTP | TCP | 8080 | 0.0.0.0/0 | Health checks (optional) |

**Note**: Destination can be restricted to VPC endpoint ENI IPs for tighter security.

### Inbound Rules

No inbound rules needed (you're the client, making outbound requests).

## Multi-Region Setup

### Scenario 1: Connect from All Regions (Recommended)

Create a VPC endpoint in each region where you have workloads:

```
Your us-east-1 VPC → PrivateLink → us-east-1 GPU cluster (lowest latency)
Your us-east-2 VPC → PrivateLink → us-east-2 GPU cluster
Your us-west-2 VPC → PrivateLink → us-west-2 GPU cluster
```

**Cost**: $21.60/month per region × 3 = $64.80/month
**Benefit**: Lowest latency, highest availability

### Scenario 2: Connect from One Region

Create a VPC endpoint in only your primary region:

```
Your us-east-1 VPC → PrivateLink → us-east-1 GPU cluster
```

**Cost**: $21.60/month
**Risk**: If us-east-1 fails, you have no access to GPU cluster

### Scenario 3: Cross-Region Failover

Use Transit Gateway or VPC Peering to access GPU cluster in another region:

```
Your us-east-1 VPC → Transit Gateway → us-west-2 VPC → PrivateLink → us-west-2 GPU cluster
```

**Cost**: $21.60/month + TGW data transfer
**Use case**: DR scenario only (higher latency)

## Cost

### PrivateLink Costs

| Component | Cost | Calculation |
|-----------|------|-------------|
| **VPC Endpoint** | $0.01/hour per AZ | $0.01 × 24 × 30 × 3 AZs = **$21.60/month** |
| **Data Transfer** | $0.01/GB | 1,000 GB = **$10/month** |
| **Total** | | **$31.60/month** |

**vs Public Internet**:
- PrivateLink: $31.60/month
- Public Internet: $0/month for endpoint, but ~$50/month data transfer (0.05/GB outbound)
- **Savings with PrivateLink**: ~$18/month + better security/latency

## Monitoring

### CloudWatch Metrics (Your Side)

Monitor these metrics in your account:

```bash
# VPC Endpoint metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/PrivateLink \
  --metric-name PacketsTransferred \
  --dimensions Name=VPC Endpoint Id,Value=vpce-xxx \
  --start-time 2025-01-28T00:00:00Z \
  --end-time 2025-01-28T23:59:59Z \
  --period 3600 \
  --statistics Sum
```

### Application-Level Monitoring

Track:
- **Latency**: Should be 140-160ms (vs 160-180ms over internet)
- **Error rate**: < 0.1%
- **Timeout rate**: < 0.01%
- **Connection failures**: 0

## Troubleshooting

### Issue: VPC Endpoint Stuck in "pendingAcceptance"

**Cause**: Awaiting approval from GPU cluster team
**Solution**: Contact support, wait up to 4 hours

### Issue: Cannot connect to private IPs

**Checks**:
1. VPC endpoint state is `available`
2. Security group allows outbound TCP 443/8080
3. Route tables allow traffic to VPC endpoint
4. Private IPs are correct (query ENIs)

```bash
# Check VPC endpoint state
aws ec2 describe-vpc-endpoints --vpc-endpoint-ids vpce-xxx

# Check security group rules
aws ec2 describe-security-groups --group-ids sg-xxx

# Test connectivity from EC2 instance in same VPC
ssh ec2-instance
curl -v http://10.34.10.50:8080/health
```

### Issue: High latency over PrivateLink

**Expected**: 140-160ms (should be 5-10ms faster than internet)
**If higher**:
- Check if connecting to correct region
- Verify subnets are in same AZ as workload
- Test from multiple AZs

### Issue: Connection timeouts

**Checks**:
1. GPU cluster has capacity (check /health endpoint)
2. Request size < 10MB
3. Timeout set to 30+ seconds
4. No network ACLs blocking traffic

## Best Practices

1. **Use 3 subnets** (one per AZ) for high availability
2. **Enable private DNS** for easier management
3. **Monitor latency** and compare to public internet
4. **Test failover** by disabling one subnet
5. **Use VPC endpoint policy** to restrict access to specific services
6. **Tag endpoints** for cost allocation
7. **Set up CloudWatch alarms** for connection issues

## Support

**Issues with VPC Endpoint Setup**:
- Email: gpu-cluster-support@yourcompany.com
- Slack: #gpu-cluster-support

**Issues with GPU Cluster Connectivity**:
- After PrivateLink is working
- See [Tenant API Documentation](./api/tenant-api.md)

## Migration from Public to PrivateLink

### Phase 1: Set up PrivateLink (1-2 hours)
1. Create VPC endpoint
2. Wait for approval
3. Test connectivity with private IPs

### Phase 2: Update application (1 day)
1. Add private IPs to configuration
2. Test in staging environment
3. Monitor latency and errors

### Phase 3: Production cutover (1 hour)
1. Deploy updated configuration to production
2. Monitor for 24 hours
3. Remove public IP configuration

### Rollback Plan
Keep public IPs configured for 1 week in case of issues.

## FAQ

**Q: Can I use both public and private connectivity?**
A: Yes, but choose one as primary. Use the other for DR.

**Q: Does PrivateLink work across regions?**
A: Each VPC endpoint connects to one region. Create multiple endpoints for multi-region access.

**Q: What if my VPC endpoint fails?**
A: With 3 subnets, you have 3 ENIs. If one fails, traffic routes to others automatically.

**Q: Can I connect from on-premises?**
A: Yes, via AWS Direct Connect or VPN to your VPC, then through PrivateLink.

**Q: How do I know which GPU region served my request?**
A: Check the `X-Region` response header.

**Q: Does PrivateLink support IPv6?**
A: Yes, but our GPU cluster currently uses IPv4 only.

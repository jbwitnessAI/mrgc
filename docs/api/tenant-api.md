# Tenant API Documentation

## Overview

Tenants connect to the Multi-Region GPU Cluster using AWS Global Accelerator's static anycast IP addresses. All requests are encrypted using tenant-specific KMS keys and decrypted inside AWS Nitro Enclaves.

## Connection Endpoints

### Static Anycast IPs

After deployment, you will receive **2 static IPv4 addresses**:

```
Primary IP:   75.2.60.100  (example)
Secondary IP: 75.2.61.200  (example)
```

**These IPs never change**, even if we add/remove regions or make infrastructure changes.

### DNS (Alternative)

Alternatively, you can use the Global Accelerator DNS name:

```
DNS: a1234567890abcdef.awsglobalaccelerator.com
```

**Recommendation**: Use the static IPs directly for lowest latency. DNS adds ~5-10ms for resolution.

## API Endpoints

### POST /inference

Submit an encrypted inference request to the GPU cluster.

**URL**: `https://{STATIC_IP}:443/inference`

**Method**: `POST`

**Headers**:
```
Content-Type: application/octet-stream
X-Tenant-ID: {your-tenant-id}
X-KMS-Key-ID: {your-kms-key-arn}
X-Model-Pool: {model-pool-name}
X-Request-ID: {unique-request-id}
```

**Body**: Encrypted payload (binary)

**Request Flow**:
```
1. Tenant encrypts request with their KMS key
2. POST to https://75.2.60.100:443/inference
3. Global Accelerator routes to nearest healthy region
4. Regional Router selects best GPU instance
5. Nitro Enclave decrypts request using tenant's KMS key
6. Parent instance runs inference on GPU
7. Nitro Enclave encrypts response
8. Response returned to tenant
```

**Example** (Python):
```python
import boto3
import requests

# Initialize KMS client
kms = boto3.client('kms', region_name='us-east-1')

# Your request payload
payload = {
    "prompt": "Explain quantum computing",
    "max_tokens": 500,
    "temperature": 0.7
}

# Encrypt with your KMS key
response = kms.encrypt(
    KeyId='arn:aws:kms:us-east-1:123456789012:key/your-key-id',
    Plaintext=json.dumps(payload).encode('utf-8')
)

encrypted_payload = response['CiphertextBlob']

# Send to GPU cluster
response = requests.post(
    'https://75.2.60.100:443/inference',
    headers={
        'Content-Type': 'application/octet-stream',
        'X-Tenant-ID': 'tenant-12345',
        'X-KMS-Key-ID': 'arn:aws:kms:us-east-1:123456789012:key/your-key-id',
        'X-Model-Pool': 'model-a',
        'X-Request-ID': str(uuid.uuid4())
    },
    data=encrypted_payload,
    timeout=30
)

# Decrypt response
encrypted_response = response.content
decrypted = kms.decrypt(CiphertextBlob=encrypted_response)
result = json.loads(decrypted['Plaintext'])

print(result)
```

**Response**: Encrypted payload (binary)

**Status Codes**:
- `200 OK`: Success, response is encrypted
- `400 Bad Request`: Invalid request format
- `401 Unauthorized`: KMS key validation failed
- `429 Too Many Requests`: Rate limit exceeded
- `500 Internal Server Error`: Processing error
- `503 Service Unavailable`: No healthy GPUs available

### GET /health

Check cluster health (public endpoint, no encryption).

**URL**: `http://{STATIC_IP}:8080/health`

**Method**: `GET`

**Response**:
```json
{
  "status": "healthy",
  "region": "us-east-1",
  "available_capacity": 45,
  "total_capacity": 50,
  "avg_queue_depth": 2.3,
  "timestamp": 1699564800
}
```

**Status Codes**:
- `200 OK`: Cluster is healthy
- `503 Service Unavailable`: Cluster is degraded or failing over

## Security

### Encryption

All inference requests and responses are encrypted using **your KMS key**:

1. **Tenant encrypts** request before sending
2. **Nitro Enclave decrypts** using tenant's KMS key (with attestation)
3. **Parent instance** processes plaintext (NEVER sees KMS key)
4. **Nitro Enclave encrypts** response
5. **Tenant decrypts** response

**Security Properties**:
- Infrastructure team **cannot access** your data (Nitro Enclave isolation)
- AWS **cannot access** your data (even with root access)
- Each request uses **unique encryption** (via KMS)
- Cryptographic **attestation** verifies Nitro Enclave code

### KMS Key Requirements

Your KMS key must:
- Be in the same region as your tenant VPC (us-east-1, us-east-2, or us-west-2)
- Grant `kms:Decrypt` permission to the Nitro Enclave IAM role
- Have a key policy allowing attestation-based access

**Example KMS Key Policy**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Allow Nitro Enclave",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::987654321098:role/mrgc-nitro-enclave-role"
      },
      "Action": [
        "kms:Decrypt"
      ],
      "Resource": "*",
      "Condition": {
        "StringEqualsIgnoreCase": {
          "kms:RecipientAttestation:ImageSha384": "ENCLAVE_IMAGE_HASH"
        }
      }
    }
  ]
}
```

### Rate Limiting

Per-tenant rate limits:
- **Burst**: Up to 10 RPS for 30 seconds
- **Sustained**: 1.5 RPS average
- **Exceeded**: HTTP 429 response, retry after 60 seconds

## Network Configuration

### Option 1: Public Internet (Not Recommended)

```
Tenant App → Internet → Global Accelerator → GPU Cluster
```

**Latency**: Baseline + ~20-50ms (internet routing)

### Option 2: AWS PrivateLink (Recommended)

```
Tenant VPC → VPC Endpoint → Global Accelerator → GPU Cluster
```

**Latency**: Baseline + ~5-10ms (private AWS backbone)

**Setup**:
1. Create VPC Endpoint in your tenant VPC
2. Use endpoint IPs instead of public IPs
3. All traffic stays on AWS private network

See [PrivateLink Setup](../docs/privatelink-setup.md) for details.

## Latency

Expected end-to-end latency (P95):

| Tenant Region | Target Region | Latency | Notes |
|--------------|---------------|---------|-------|
| us-east-1 | us-east-1 | 150ms | Same region (optimal) |
| us-east-1 | us-east-2 | 165ms | +15ms cross-region |
| us-east-1 | us-west-2 | 220ms | +70ms cross-country |
| us-west-2 | us-west-2 | 150ms | Same region (optimal) |
| us-west-2 | us-east-2 | 205ms | +55ms cross-country |

**Breakdown**:
- Network: 10-20ms (intra-region) or 15-80ms (cross-region)
- Global Accelerator: 5-10ms
- Decryption (Nitro Enclave): 20-30ms
- Inference: 100-500ms (model-dependent)
- Encryption: 20-30ms

## Failover Behavior

### Automatic Regional Failover

If a region fails, Global Accelerator **automatically** routes your traffic to the next healthy region:

```
Normal:
  Your request → us-east-1 (150ms latency)

During us-east-1 failure:
  Your request → us-east-2 (165ms latency, +15ms)

After recovery:
  Your request → us-east-1 (150ms latency)
```

**Your application code does not change** - continue using the same static IPs.

**Failover Time**: 60-90 seconds
- Detection: 60 seconds (3 failed health checks at 30s intervals)
- Routing update: < 30 seconds

### What You'll Experience

During a regional failure:
1. **T+0 to T+60s**: Normal requests complete successfully
2. **T+60s to T+90s**: Some requests may timeout (failover in progress)
3. **T+90s onwards**: All requests route to healthy region (+15-70ms latency)
4. **Recovery**: Gradual return to normal routing over 5-10 minutes

**Recommendation**: Implement retry logic with exponential backoff:

```python
import time
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=1,  # 1s, 2s, 4s
    status_forcelist=[500, 502, 503, 504, 429]
)
session.mount('https://', HTTPAdapter(max_retries=retries))

# Will automatically retry on failures
response = session.post('https://75.2.60.100:443/inference', ...)
```

## Monitoring

### Client-Side Metrics to Track

1. **Request Latency**: P50, P95, P99
2. **Error Rate**: 4xx and 5xx responses
3. **Timeout Rate**: Requests exceeding 30 seconds
4. **Regional Distribution**: Which region served your request (from `X-Region` response header)

### Response Headers

```
X-Region: us-east-1
X-Instance-ID: i-1234567890abcdef0
X-Request-Duration-Ms: 156
X-Queue-Time-Ms: 12
```

## Best Practices

1. **Use both static IPs**: Configure primary and secondary IPs for redundancy
2. **Implement retries**: Use exponential backoff for transient failures
3. **Set timeouts**: Use 30-second timeout (inference + network)
4. **Monitor latency**: Track P95 latency and alert on degradation
5. **Rotate KMS keys**: Rotate your KMS keys every 90 days
6. **Use PrivateLink**: For lowest latency and highest security
7. **Generate unique request IDs**: For tracing and debugging

## Support

**Issue Tracking**:
- Email: gpu-cluster-support@your-company.com
- Slack: #gpu-cluster-support
- Pagerduty: For production issues

**SLA**: 99.99% availability (4.3 minutes downtime per month)

**Incident Response**:
- P0 (cluster down): < 15 minutes
- P1 (degraded performance): < 1 hour
- P2 (minor issues): < 4 hours

## Examples

### Complete Request/Response Example

```python
import boto3
import requests
import json
import uuid

# Configuration
STATIC_IP = "75.2.60.100"
TENANT_ID = "tenant-12345"
KMS_KEY_ARN = "arn:aws:kms:us-east-1:123456789012:key/abcd-1234"
MODEL_POOL = "model-a"

# Initialize KMS
kms = boto3.client('kms', region_name='us-east-1')

# Request payload
payload = {
    "prompt": "Write a haiku about cloud computing",
    "max_tokens": 50
}

# Encrypt request
encrypted_request = kms.encrypt(
    KeyId=KMS_KEY_ARN,
    Plaintext=json.dumps(payload).encode()
)['CiphertextBlob']

# Send to GPU cluster
response = requests.post(
    f'https://{STATIC_IP}:443/inference',
    headers={
        'Content-Type': 'application/octet-stream',
        'X-Tenant-ID': TENANT_ID,
        'X-KMS-Key-ID': KMS_KEY_ARN,
        'X-Model-Pool': MODEL_POOL,
        'X-Request-ID': str(uuid.uuid4())
    },
    data=encrypted_request,
    timeout=30
)

# Decrypt response
if response.status_code == 200:
    decrypted_response = kms.decrypt(
        CiphertextBlob=response.content
    )['Plaintext']

    result = json.loads(decrypted_response)
    print(f"Response: {result['text']}")
    print(f"Region: {response.headers.get('X-Region')}")
    print(f"Latency: {response.headers.get('X-Request-Duration-Ms')}ms")
else:
    print(f"Error: HTTP {response.status_code}")
    print(response.text)
```

## Changelog

- **2025-01-15**: Initial API documentation
- **2025-01-20**: Added PrivateLink configuration
- **2025-01-25**: Updated failover behavior details

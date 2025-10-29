# FSx Lustre Setup Guide

## Overview

FSx Lustre provides high-performance shared storage for LLM models across all GPU instances in each region. This eliminates the need for per-instance model storage and dramatically reduces model loading times.

## Benefits

| Feature | FSx Lustre | EBS (per instance) | S3 Direct |
|---------|------------|-------------------|-----------|
| **Shared across instances** | ✅ Yes | ❌ No | ✅ Yes |
| **Load time (7B model)** | 5-10s (cached) | 30-45s | 2-3 minutes |
| **Load time (70B model)** | 45-60s (cached) | 5-7 minutes | 15-20 minutes |
| **Throughput per instance** | 1-2 GB/s | 250-1000 MB/s | 100-500 MB/s |
| **Cost** | $206/month (shared) | $100/month × N instances | Free (API calls) |
| **S3 sync** | Automatic | Manual | N/A |
| **Latency** | < 1ms | < 1ms | 10-100ms |

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│ S3 Bucket (mrgc-models-use1)                             │
│ - Authoritative source for models                        │
│ - Cross-region replication                               │
└────────────────────┬─────────────────────────────────────┘
                     │
                     │ Auto-sync (bidirectional)
                     ↓
┌──────────────────────────────────────────────────────────┐
│ FSx Lustre (fs-xxxxx.fsx.us-east-1.amazonaws.com)       │
│ - 1.2 TB SSD storage                                     │
│ - 200 MB/s/TiB throughput                                │
│ - Multi-AZ deployment                                    │
│ - Automatic S3 import/export                             │
└────────────────────┬─────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ↓            ↓            ↓
┌──────────┐  ┌──────────┐  ┌──────────┐
│ GPU      │  │ GPU      │  │ GPU      │
│ Instance │  │ Instance │  │ Instance │
│          │  │          │  │          │
│ Mount:   │  │ Mount:   │  │ Mount:   │
│ /fsx     │  │ /fsx     │  │ /fsx     │
└──────────┘  └──────────┘  └──────────┘
```

## FSx File System Structure

```
/fsx/
├── models/
│   ├── model-a/          # Llama 2 7B
│   │   ├── config.json
│   │   ├── pytorch_model.bin
│   │   ├── tokenizer.json
│   │   └── tokenizer_config.json
│   ├── model-b/          # Mistral 7B Instruct
│   ├── model-c/          # CodeLlama 13B
│   └── model-d/          # Llama 2 70B
└── metadata/
    ├── model-registry.json  # Central registry
    └── checksums.json       # Model checksums
```

## Setup Instructions

### 1. Deploy FSx with Terraform

```bash
cd infrastructure/terraform/environments/production

# Edit terraform.tfvars
cat >> terraform.tfvars <<EOF
# FSx Lustre configuration
fsx_storage_capacity_gb      = 1200
fsx_per_unit_throughput      = 200
fsx_deployment_type          = "PERSISTENT_1"
fsx_storage_type             = "SSD"
fsx_backup_retention_days    = 7
EOF

# Apply Terraform
terraform apply -target=module.fsx_lustre
```

### 2. Create S3 Bucket for Data Repository

```bash
# Create S3 bucket (if not using Terraform)
aws s3 mb s3://mrgc-models-use1 --region us-east-1

# Enable versioning
aws s3api put-bucket-versioning \
  --bucket mrgc-models-use1 \
  --versioning-configuration Status=Enabled \
  --region us-east-1

# Enable encryption
aws s3api put-bucket-encryption \
  --bucket mrgc-models-use1 \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }' \
  --region us-east-1
```

### 3. Mount FSx on GPU Instances

```bash
# On each GPU instance

# Install Lustre client
sudo amazon-linux-extras install -y lustre

# Create mount point
sudo mkdir -p /fsx

# Get FSx DNS name from Terraform output or AWS Console
FSX_DNS_NAME="fs-0123456789abcdef0.fsx.us-east-1.amazonaws.com"
FSX_MOUNT_NAME="fsx"

# Mount FSx
sudo mount -t lustre ${FSX_DNS_NAME}@tcp:/${FSX_MOUNT_NAME} /fsx

# Verify mount
df -h | grep fsx
ls -l /fsx/

# Add to /etc/fstab for auto-mount on boot
echo "${FSX_DNS_NAME}@tcp:/${FSX_MOUNT_NAME} /fsx lustre defaults,_netdev 0 0" | sudo tee -a /etc/fstab
```

### 4. Upload Models to FSx

```bash
# Method 1: Upload to S3, FSx auto-imports
aws s3 sync /local/models/llama-2-7b/ s3://mrgc-models-use1/model-a/
# Wait 1-2 minutes for FSx to import

# Method 2: Direct upload to FSx (from any GPU instance)
scp -r /local/models/llama-2-7b/ gpu-instance:/fsx/models/model-a/

# Method 3: Use our upload script
./scripts/model-management/upload-model.sh \
  --model-path /local/models/llama-2-7b \
  --model-pool model-a \
  --model-name "Llama 2 7B" \
  --region us-east-1 \
  --s3-bucket mrgc-models-use1 \
  --fsx-id fs-0123456789abcdef0 \
  --preload true
```

### 5. Create Model Registry

```bash
# SSH to any GPU instance
ssh gpu-instance

# Create registry
python3 /opt/mrgc/scripts/model-management/manage-model-registry.py add \
  --model-pool model-a \
  --name "Llama 2 7B" \
  --path /fsx/models/model-a \
  --size-gb 13.5 \
  --preload \
  --s3-source s3://mrgc-models-use1/model-a/

# List models
python3 /opt/mrgc/scripts/model-management/manage-model-registry.py list

# Validate all models
python3 /opt/mrgc/scripts/model-management/manage-model-registry.py validate
```

## Model Loading Performance

### First Load (from S3 via FSx)

| Model Size | Initial Load Time | Notes |
|------------|-------------------|-------|
| 7B parameters | 30-45 seconds | Imports from S3 to FSx |
| 13B parameters | 60-90 seconds | Imports from S3 to FSx |
| 70B parameters | 5-7 minutes | Imports from S3 to FSx |

### Cached Load (from FSx)

| Model Size | Cached Load Time | Notes |
|------------|------------------|-------|
| 7B parameters | 5-10 seconds | Reads from FSx cache |
| 13B parameters | 10-15 seconds | Reads from FSx cache |
| 70B parameters | 45-60 seconds | Reads from FSx cache |

## Cost Breakdown

### Per Region (1.2 TB)

| Component | Cost | Calculation |
|-----------|------|-------------|
| Storage (SSD) | $168/month | 1200 GB × $0.14/GB |
| Throughput (200 MB/s/TiB) | $30/month | ~200 MB/s × $0.13 |
| Backups (~50 GB) | $8/month | 50 GB × $0.05/GB |
| **Total** | **$206/month** | Per region |

### All 3 Regions

- Total: **$618/month** ($206 × 3)

### vs. EBS Alternative

- EBS per instance: ~$100/month × 10 instances = **$1,000/month**
- FSx shared: **$206/month**
- **Savings: ~80%** ($794/month per region)

## Monitoring

### CloudWatch Metrics

```bash
# Storage capacity
aws cloudwatch get-metric-statistics \
  --namespace AWS/FSx \
  --metric-name FreeStorageCapacity \
  --dimensions Name=FileSystemId,Value=fs-xxxxx \
  --start-time 2025-01-28T00:00:00Z \
  --end-time 2025-01-28T23:59:59Z \
  --period 3600 \
  --statistics Average \
  --region us-east-1

# Read throughput
aws cloudwatch get-metric-statistics \
  --namespace AWS/FSx \
  --metric-name DataReadBytes \
  --dimensions Name=FileSystemId,Value=fs-xxxxx \
  --start-time 2025-01-28T00:00:00Z \
  --end-time 2025-01-28T23:59:59Z \
  --period 3600 \
  --statistics Sum \
  --region us-east-1
```

### FSx Commands

```bash
# Check FSx mount
df -h | grep fsx

# Test read performance
sudo lfs setstripe -c -1 /fsx/test_file
dd if=/dev/zero of=/fsx/test_file bs=1M count=1024 oflag=direct
# Should see ~1-2 GB/s write speed

# Test read performance
dd if=/fsx/test_file of=/dev/null bs=1M iflag=direct
# Should see ~1-2 GB/s read speed

# Clean up
rm /fsx/test_file

# Check FSx data repository tasks
aws fsx describe-data-repository-tasks \
  --filters Name=file-system-id,Values=fs-xxxxx \
  --region us-east-1
```

## Troubleshooting

### Issue: FSx not mounting

**Check:**
1. Lustre client installed: `rpm -qa | grep lustre`
2. Security groups allow Lustre traffic (ports 988, 1021-1023)
3. FSx file system is available: `aws fsx describe-file-systems`

```bash
# Install Lustre client
sudo amazon-linux-extras install -y lustre

# Check security groups
aws ec2 describe-security-groups --group-ids sg-xxxxx

# Verify FSx status
aws fsx describe-file-systems --file-system-ids fs-xxxxx
```

### Issue: S3 import not working

**Check:**
1. FSx has IAM role with S3 permissions
2. S3 bucket is in same region as FSx
3. Data repository association exists

```bash
# Check data repository associations
aws fsx describe-data-repository-associations \
  --filters Name=file-system-id,Values=fs-xxxxx

# Manually trigger import
aws fsx create-data-repository-task \
  --file-system-id fs-xxxxx \
  --type IMPORT_METADATA_FROM_REPOSITORY \
  --paths /model-a/
```

### Issue: Slow model loading

**Symptoms**: Model loading takes > 60 seconds

**Checks**:
1. Check if model is cached: First load is slower
2. Check FSx throughput utilization
3. Check network bandwidth to FSx
4. Verify multiple instances aren't loading simultaneously

```bash
# Check FSx metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/FSx \
  --metric-name DataReadBytes \
  --dimensions Name=FileSystemId,Value=fs-xxxxx \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum

# Check network from instance
iperf3 -c ${FSX_DNS_NAME}
```

## Best Practices

1. **Always use S3 as the source of truth**
   - Upload models to S3 first
   - Let FSx auto-import from S3
   - This ensures consistency across regions

2. **Preload frequently-used models**
   - Set `preload: true` in model registry
   - Instances load these models on startup
   - Avoids first-request latency

3. **Monitor storage capacity**
   - Set CloudWatch alarm for < 15% free
   - Delete old models or increase capacity
   - FSx can scale to 100s of TB

4. **Test failover scenarios**
   - Unmount and remount FSx
   - Verify models load from S3 if FSx fails
   - Test DR procedures regularly

5. **Use cross-region S3 replication**
   - Replicate model S3 buckets across regions
   - Enables fast DR recovery
   - FSx can import from replicated bucket

6. **Keep model registry updated**
   - Update registry when adding/removing models
   - Validate registry regularly
   - Use scripts for consistency

## Multi-Region Setup

### Per-Region FSx

Each region has its own FSx file system:

```
us-east-1:  fs-xxxxx.fsx.us-east-1.amazonaws.com → s3://mrgc-models-use1/
us-east-2:  fs-yyyyy.fsx.us-east-2.amazonaws.com → s3://mrgc-models-use2/
us-west-2:  fs-zzzzz.fsx.us-west-2.amazonaws.com → s3://mrgc-models-usw2/
```

### S3 Cross-Region Replication

```bash
# Enable replication from us-east-1 to us-east-2, us-west-2
aws s3api put-bucket-replication \
  --bucket mrgc-models-use1 \
  --replication-configuration file://replication-config.json
```

**replication-config.json:**
```json
{
  "Role": "arn:aws:iam::ACCOUNT:role/s3-replication-role",
  "Rules": [
    {
      "Status": "Enabled",
      "Priority": 1,
      "Destination": {
        "Bucket": "arn:aws:s3:::mrgc-models-use2"
      }
    },
    {
      "Status": "Enabled",
      "Priority": 2,
      "Destination": {
        "Bucket": "arn:aws:s3:::mrgc-models-usw2"
      }
    }
  ]
}
```

## Next Steps

After setting up FSx:
1. Upload all models to S3
2. Wait for FSx auto-import (1-2 minutes)
3. Create model registry on FSx
4. Test model loading from GPU instances
5. Set up Regional Router to use models
6. Configure auto-scaling
7. Implement Car Wash cleanup

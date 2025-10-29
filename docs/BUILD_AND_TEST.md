# Build and Test Guide

## Overview

This guide walks through building and testing the Multi-Region GPU Cluster incrementally, from local development to full AWS deployment.

## Testing Levels

```
Level 1: Local Testing (No AWS)          ← Start here
   ↓
Level 2: Single Component Testing (AWS)
   ↓
Level 3: Single Region Testing (AWS)
   ↓
Level 4: Multi-Region Testing (AWS)
   ↓
Level 5: Production Load Testing
```

---

## Level 1: Local Testing (No AWS Required)

Test individual components locally without AWS resources.

### 1.1 Test Python Applications Locally

```bash
cd /Users/johnbutler/claude/mrgc

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies for each app
cd applications/global-state
pip install -r requirements.txt
python state_manager.py  # Should run without errors

cd ../regional-router
pip install -r requirements.txt
python router_app.py  # Will fail connecting to DynamoDB (expected)

cd ../autoscaler
pip install -r requirements.txt
python autoscaler.py --region us-east-1  # Test logic

cd ../car-wash
pip install -r requirements.txt
python carwash.py  # Run test cleanup
```

### 1.2 Test Nitro Enclave Application (Mock Mode)

```bash
cd applications/nitro-enclave

# Install dependencies
pip install -r requirements.txt

# Test enclave app in mock mode (no real NSM)
python enclave_app.py
# Will run vsock server in development mode
```

### 1.3 Validate Terraform Configuration

```bash
cd infrastructure/terraform/environments/production

# Initialize Terraform
terraform init

# Validate syntax
terraform validate
# Should output: Success! The configuration is valid.

# Plan (will fail due to missing variables, but checks syntax)
terraform plan
```

### 1.4 Test Model Registry Manager

```bash
cd scripts/model-management

# Create local test registry
mkdir -p /tmp/fsx-test/metadata

# Test registry operations
python manage-model-registry.py --registry-path /tmp/fsx-test/metadata/registry.json add \
  --model-pool test-model \
  --name "Test Model" \
  --path /tmp/fsx-test/models/test \
  --size-gb 1.0

# List models
python manage-model-registry.py --registry-path /tmp/fsx-test/metadata/registry.json list

# Cleanup
rm -rf /tmp/fsx-test
```

**Expected Results:**
- ✅ Python apps run without syntax errors
- ✅ Terraform validates successfully
- ✅ Model registry operations work
- ⚠️ AWS connection errors are expected (we're testing locally)

---

## Level 2: Single Component Testing (AWS)

Deploy and test individual components in AWS.

### 2.1 Prerequisites

```bash
# Install AWS CLI
brew install awscli  # macOS
# sudo apt-get install awscli  # Linux

# Configure AWS credentials
aws configure
# Enter: Access Key ID, Secret Key, Region (us-east-1), Output (json)

# Verify access
aws sts get-caller-identity
# Should show your AWS account ID

# Install Terraform
brew install terraform  # macOS

# Install Docker
# Download from: https://www.docker.com/products/docker-desktop
```

### 2.2 Test DynamoDB Global Tables (Feature 1B)

```bash
cd infrastructure/terraform/environments/production

# Create terraform.tfvars
cat > terraform.tfvars <<EOF
cluster_name = "mrgc-test"
environment  = "dev"

# Single region for testing
regions = ["us-east-1"]

# Minimal configuration
vpc_cidr_base = "10.66.0.0/16"

# Tags
tags = {
  Project     = "MRGC"
  Environment = "dev"
  ManagedBy   = "terraform"
}
EOF

# Deploy only DynamoDB
terraform init
terraform plan -target=module.dynamodb
terraform apply -target=module.dynamodb

# Verify tables created
aws dynamodb list-tables --region us-east-1 | grep mrgc
```

**Test DynamoDB with Python:**

```bash
cd applications/global-state

# Set AWS region
export AWS_REGION=us-east-1

# Test state manager
python3 <<EOF
from state_manager import StateManager

# Create state manager
mgr = StateManager(region='us-east-1')

# Test GPU instance registration
mgr.register_gpu_instance(
    instance_id='i-test123',
    region='us-east-1',
    availability_zone='us-east-1a',
    private_ip='10.66.1.10',
    instance_type='g6e.2xlarge'
)

# List instances
instances = mgr.list_gpu_instances()
print(f"Found {len(instances)} instances")

# Cleanup
mgr.delete_gpu_instance('i-test123')
EOF
```

**Expected Results:**
- ✅ DynamoDB tables created
- ✅ Python can read/write to DynamoDB
- ✅ No errors in CloudWatch logs

### 2.3 Test VPC and Networking (Feature 1A)

```bash
# Deploy VPC in single region
terraform apply -target=module.vpc

# Verify VPC created
aws ec2 describe-vpcs --filters "Name=tag:Name,Values=mrgc-test-vpc-use1" --region us-east-1

# Check subnets
aws ec2 describe-subnets --filters "Name=tag:Project,Values=MRGC" --region us-east-1
```

**Expected Results:**
- ✅ VPC created with CIDR 10.66.0.0/18
- ✅ 12 subnets across 3 AZs (public, private, FSx, TGW)
- ✅ NAT Gateways, Internet Gateway created

### 2.4 Test FSx Lustre (Feature 4)

```bash
# Deploy FSx
terraform apply -target=module.fsx_lustre

# Get FSx DNS name
terraform output fsx_dns_name

# Note: This takes 5-10 minutes to create
```

**Test FSx Mount (requires EC2 instance):**

```bash
# Launch test EC2 instance in same VPC
aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \
  --instance-type t3.micro \
  --subnet-id <subnet-id> \
  --key-name <your-key> \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=mrgc-test-instance}]'

# SSH to instance
ssh ec2-user@<instance-ip>

# Install Lustre client
sudo amazon-linux-extras install -y lustre

# Mount FSx
FSX_DNS=<dns-from-terraform-output>
sudo mkdir -p /fsx
sudo mount -t lustre ${FSX_DNS}@tcp:/fsx /fsx

# Test read/write
echo "test" | sudo tee /fsx/test.txt
cat /fsx/test.txt
# Should output: test

# Cleanup
sudo umount /fsx
exit
```

**Expected Results:**
- ✅ FSx file system created
- ✅ Can mount from EC2 instance
- ✅ Read/write operations work

---

## Level 3: Single Region Testing (AWS)

Deploy full stack in one region and test end-to-end.

### 3.1 Deploy Full Single-Region Stack

```bash
cd infrastructure/terraform/environments/production

# Update terraform.tfvars for single region full deployment
cat >> terraform.tfvars <<EOF
# GPU instances
gpu_instance_count = 1  # Start with 1 for testing
gpu_instance_type  = "g6e.2xlarge"

# FSx Lustre
fsx_storage_capacity_gb = 1200

# Regional Router
regional_router_cpu    = 512
regional_router_memory = 1024
EOF

# Deploy everything
terraform apply
```

**This will create:**
- ✅ VPC with subnets
- ✅ DynamoDB Global Tables
- ✅ FSx Lustre (1.2 TB)
- ✅ NLB
- ✅ ECS cluster for Regional Router
- ✅ 1 GPU instance (g6e.2xlarge)

**Cost:** ~$1.50/hour for testing

### 3.2 Build and Deploy Nitro Enclave

```bash
# SSH to GPU instance
GPU_INSTANCE_IP=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=mrgc-test-gpu-*" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)

ssh ec2-user@${GPU_INSTANCE_IP}

# On GPU instance:
# Copy enclave code
scp -r applications/nitro-enclave/* ec2-user@${GPU_INSTANCE_IP}:/home/ec2-user/

# Build enclave
cd /home/ec2-user/nitro-enclave
./build.sh

# Run enclave
sudo nitro-cli run-enclave \
  --eif-path mrgc-enclave.eif \
  --memory 4096 \
  --cpu-count 2 \
  --debug-mode

# Check enclave status
sudo nitro-cli describe-enclaves
# Should show State: RUNNING

# View enclave logs
sudo nitro-cli console --enclave-id <enclave-id>
```

### 3.3 Deploy Parent Instance Application

```bash
# On GPU instance:
cd /home/ec2-user
git clone https://github.com/jbwitnessAI/mrgc.git
cd mrgc/applications/parent-instance

# Install dependencies
pip3 install -r requirements.txt

# Mount FSx Lustre
FSX_DNS=$(aws fsx describe-file-systems \
  --query 'FileSystems[0].DNSName' \
  --output text)

sudo mkdir -p /fsx
sudo mount -t lustre ${FSX_DNS}@tcp:/fsx /fsx

# Start parent app
python3 parent_app.py &

# Test health endpoint
curl http://localhost:8080/health
# Should return: {"status": "healthy", ...}
```

### 3.4 Deploy Regional Router

```bash
cd applications/regional-router

# Build Docker image
docker build -t regional-router .

# Push to ECR
aws ecr create-repository --repository-name mrgc-regional-router
aws ecr get-login-password | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
docker tag regional-router:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/mrgc-regional-router:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/mrgc-regional-router:latest

# Deploy to ECS (using Terraform)
terraform apply -target=module.regional_router
```

### 3.5 End-to-End Test

```bash
# Get NLB DNS name
NLB_DNS=$(aws elbv2 describe-load-balancers \
  --names mrgc-test-nlb-use1 \
  --query 'LoadBalancers[0].DNSName' \
  --output text)

# Create test encrypted payload
python3 <<EOF
import boto3
import json
import requests

# Create KMS key for testing
kms = boto3.client('kms', region_name='us-east-1')
key = kms.create_key(Description='MRGC test key')
key_arn = key['KeyMetadata']['Arn']

# Encrypt test payload
payload = {"prompt": "Hello, world!", "max_tokens": 50}
encrypted = kms.encrypt(
    KeyId=key_arn,
    Plaintext=json.dumps(payload).encode()
)['CiphertextBlob']

# Send to cluster
nlb_dns = "${NLB_DNS}"
response = requests.post(
    f'http://{nlb_dns}:8080/inference',
    data=encrypted,
    headers={
        'X-KMS-Key-ARN': key_arn,
        'X-Tenant-ID': 'test-tenant',
        'X-Model-Pool': 'model-a',
        'X-Request-ID': 'test-001'
    },
    timeout=30
)

print(f"Status: {response.status_code}")
print(f"Response size: {len(response.content)} bytes")

# Decrypt response
decrypted = kms.decrypt(CiphertextBlob=response.content)['Plaintext']
result = json.loads(decrypted)
print(f"Result: {result}")

# Cleanup
kms.schedule_key_deletion(KeyId=key_arn, PendingWindowInDays=7)
EOF
```

**Expected Results:**
- ✅ Status: 200
- ✅ Encrypted response received
- ✅ Response decrypts successfully
- ✅ Inference result in response

---

## Level 4: Multi-Region Testing (AWS)

Deploy across 3 regions and test failover.

### 4.1 Deploy Multi-Region

```bash
# Update terraform.tfvars
cat > terraform.tfvars <<EOF
cluster_name = "mrgc-test"
regions = ["us-east-1", "us-east-2", "us-west-2"]
gpu_instance_count = 1  # Per region
EOF

# Deploy to all regions
terraform apply

# This takes 20-30 minutes
```

### 4.2 Test Global Accelerator

```bash
# Get Global Accelerator IPs
aws globalaccelerator list-accelerators \
  --query 'Accelerators[0].IpSets[0].IpAddresses' \
  --output text

# Test from multiple locations
# IP1 and IP2 should route to nearest healthy region

# Test from different regions
for region in us-east-1 us-east-2 us-west-2; do
  echo "Testing from ${region}..."
  # Send request to Global Accelerator IP
  # Observe which region handles it
done
```

### 4.3 Test Failover

```bash
# Stop all GPU instances in us-east-1
aws ec2 stop-instances \
  --instance-ids $(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=mrgc-test-gpu-*" "Name=instance-state-name,Values=running" \
    --region us-east-1 \
    --query 'Reservations[].Instances[].InstanceId' \
    --output text) \
  --region us-east-1

# Monitor Global Accelerator failover
# Should redirect to us-east-2 or us-west-2 within 60 seconds

# Send test request
# Should succeed via healthy region

# Restart us-east-1 instances
aws ec2 start-instances --instance-ids <instance-ids> --region us-east-1

# Global Accelerator should automatically recover
```

**Expected Results:**
- ✅ Failover completes within 60 seconds
- ✅ Requests continue working via healthy regions
- ✅ Automatic recovery when region restored

---

## Level 5: Production Load Testing

Test under realistic load.

### 5.1 Load Testing Setup

```bash
# Install load testing tool
pip install locust

# Create load test script
cat > load_test.py <<'EOF'
from locust import HttpUser, task, between
import boto3
import json

class TenantUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        # Create KMS key
        self.kms = boto3.client('kms', region_name='us-east-1')
        key = self.kms.create_key(Description='Load test')
        self.key_arn = key['KeyMetadata']['Arn']

    @task
    def inference_request(self):
        # Encrypt payload
        payload = {"prompt": "Test prompt", "max_tokens": 50}
        encrypted = self.kms.encrypt(
            KeyId=self.key_arn,
            Plaintext=json.dumps(payload).encode()
        )['CiphertextBlob']

        # Send to cluster
        self.client.post(
            "/inference",
            data=encrypted,
            headers={
                'X-KMS-Key-ARN': self.key_arn,
                'X-Tenant-ID': 'load-test',
                'X-Model-Pool': 'model-a'
            }
        )
EOF

# Run load test
locust -f load_test.py --host=http://<global-accelerator-ip>:8080

# Access web UI: http://localhost:8089
# Start with 10 users, ramp to 100
```

### 5.2 Monitor Performance

```bash
# Watch CloudWatch metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/NetworkELB \
  --metric-name ActiveFlowCount \
  --dimensions Name=LoadBalancer,Value=<nlb-name> \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average Sum \
  --region us-east-1

# Check auto-scaling
aws dynamodb get-item \
  --table-name mrgc-test-autoscaling_state \
  --key '{"region": {"S": "us-east-1"}}'
```

### 5.3 Validate Auto-Scaling

```bash
# Generate high load (> 15 RPS per instance)
# After 2 minutes, should scale up

# Check instance count
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=mrgc-test-gpu-*" "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].InstanceId' \
  --region us-east-1

# Reduce load
# After 10 minutes, should scale down
```

**Expected Results:**
- ✅ P95 latency < 700ms
- ✅ Error rate < 0.1%
- ✅ Auto-scaling triggers correctly
- ✅ All regions handling load

---

## Cleanup / Teardown

```bash
# Destroy all resources
cd infrastructure/terraform/environments/production
terraform destroy

# Verify nothing left
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Values=MRGC \
  --query 'ResourceTagMappingList[].ResourceARN'

# Should return empty list
```

---

## Cost Estimation for Testing

| Phase | Duration | Cost | Notes |
|-------|----------|------|-------|
| Level 1 (Local) | Unlimited | $0 | No AWS resources |
| Level 2 (Components) | 1 hour | ~$5 | DynamoDB, VPC, FSx |
| Level 3 (Single Region) | 4 hours | ~$10 | 1 GPU instance + FSx |
| Level 4 (Multi-Region) | 8 hours | ~$40 | 3 GPU instances + infrastructure |
| Level 5 (Load Test) | 2 hours | ~$10 | Full load |
| **Total Testing** | ~15 hours | **~$65** | |

**Tips to Minimize Costs:**
- Use Spot instances for GPU instances (70% savings)
- Stop instances when not testing
- Delete FSx when not needed
- Use smaller FSx capacity for testing (1.2 TB min)

---

## Troubleshooting

### Common Issues

1. **Terraform fails with "subnet not found"**
   - Ensure VPC deployed first: `terraform apply -target=module.vpc`

2. **Enclave fails to start**
   - Check instance has Nitro Enclave enabled
   - Verify EIF file exists
   - Check memory allocation (need 4GB free)

3. **FSx mount fails**
   - Verify Lustre client installed
   - Check security groups allow ports 988, 1021-1023
   - Ensure instance in same VPC as FSx

4. **Parent app can't connect to enclave**
   - Verify enclave is running: `nitro-cli describe-enclaves`
   - Check vsock port 5000
   - View enclave logs: `nitro-cli console`

5. **KMS decrypt fails**
   - Verify KMS key policy allows GPU instance role
   - Check PCR values match (use build.sh output)
   - Ensure attestation document is valid

---

## Next Steps After Testing

1. **Security Review**
   - Audit IAM roles and policies
   - Review security groups
   - Test KMS key policies with real tenant keys

2. **Performance Optimization**
   - Tune GPU memory utilization
   - Optimize model loading
   - Test with production-size models

3. **Monitoring Setup**
   - Create CloudWatch dashboards
   - Set up alarms
   - Configure log aggregation

4. **Documentation**
   - Update with actual resource IDs
   - Document operational procedures
   - Create runbooks

5. **Production Deployment**
   - Use separate AWS accounts for prod
   - Enable MFA and CloudTrail
   - Set up backup and DR
   - Conduct security penetration testing

---

## Getting Help

If you encounter issues:

1. Check application logs in CloudWatch
2. Review Terraform state: `terraform show`
3. Validate AWS resources: `aws <service> describe-<resource>`
4. Test components individually before integration
5. Use `--debug-mode` flags where available

Good luck with your testing! 🚀

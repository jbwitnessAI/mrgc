# Deploy MRGC to Your AWS Account

Complete guide to deploy the Multi-Region GPU Cluster to your dedicated AWS account.

## Prerequisites Checklist

Before starting, ensure you have:

- [ ] AWS account with admin access
- [ ] AWS CLI installed and configured
- [ ] Terraform 1.0+ installed
- [ ] Docker installed (for building containers)
- [ ] Git repository cloned locally
- [ ] SSH key pair for EC2 instances
- [ ] Understanding of AWS costs (GPU instances are expensive!)

---

## Step 0: Prepare Your AWS Account (15 minutes)

### 0.1 Verify AWS Access

```bash
# Check you're logged into the correct AWS account
aws sts get-caller-identity

# Output should show:
# {
#   "UserId": "...",
#   "Account": "YOUR_ACCOUNT_ID",  ← Verify this is correct
#   "Arn": "..."
# }

# Set your account ID as environment variable
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Using AWS Account: ${AWS_ACCOUNT_ID}"
```

### 0.2 Check Service Quotas

GPU instances have strict quotas. Check your limits:

```bash
# Check vCPU quota for G instance types
aws service-quotas get-service-quota \
  --service-code ec2 \
  --quota-code L-DB2E81BA \
  --region us-east-1 \
  --query 'Quota.Value'

# You need at least 8 vCPUs per g6e.2xlarge instance
# For 2 instances: 16 vCPUs minimum
# For 6 instances (3 regions × 2): 48 vCPUs minimum

# If quota is too low, request increase:
echo "If quota < 48, request increase in AWS Console:"
echo "https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas/L-DB2E81BA"
```

### 0.3 Create EC2 Key Pair

```bash
# Create SSH key for accessing instances
aws ec2 create-key-pair \
  --key-name mrgc-keypair \
  --region us-east-1 \
  --query 'KeyMaterial' \
  --output text > ~/.ssh/mrgc-keypair.pem

chmod 400 ~/.ssh/mrgc-keypair.pem

echo "✓ SSH key created: ~/.ssh/mrgc-keypair.pem"
```

### 0.4 Create S3 Backend for Terraform State

```bash
# Create S3 bucket for Terraform state (globally unique name)
BUCKET_NAME="mrgc-terraform-state-${AWS_ACCOUNT_ID}"

aws s3 mb s3://${BUCKET_NAME} --region us-east-1

# Enable versioning
aws s3api put-bucket-versioning \
  --bucket ${BUCKET_NAME} \
  --versioning-configuration Status=Enabled

# Enable encryption
aws s3api put-bucket-encryption \
  --bucket ${BUCKET_NAME} \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'

# Create DynamoDB table for state locking
aws dynamodb create-table \
  --table-name mrgc-terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1

echo "✓ Terraform backend ready"
echo "  Bucket: ${BUCKET_NAME}"
echo "  Table: mrgc-terraform-locks"
```

---

## Step 1: Configure Terraform (10 minutes)

### 1.1 Navigate to Terraform Directory

```bash
cd /Users/johnbutler/claude/mrgc/infrastructure/terraform/environments/production
```

### 1.2 Create Backend Configuration

```bash
cat > backend.tf <<EOF
terraform {
  backend "s3" {
    bucket         = "mrgc-terraform-state-${AWS_ACCOUNT_ID}"
    key            = "mrgc/production/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "mrgc-terraform-locks"
  }
}
EOF
```

### 1.3 Create terraform.tfvars

Choose your deployment size:

#### Option A: Minimal (1 region, 1 instance) - ~$40/day

```bash
cat > terraform.tfvars <<EOF
# Basic Configuration
cluster_name = "mrgc"
environment  = "production"

# Regions (start with 1)
regions = ["us-east-1"]

# Instance Configuration
gpu_instance_count      = 1
gpu_instance_type       = "g6e.2xlarge"
gpu_instance_ami        = "ami-0c55b159cbfafe1f0"  # Amazon Linux 2023
gpu_instance_key_name   = "mrgc-keypair"

# Networking
vpc_cidr_base = "10.66.0.0/16"

# FSx Lustre
fsx_storage_capacity_gb      = 1200
fsx_per_unit_throughput      = 200
fsx_deployment_type          = "PERSISTENT_1"
fsx_backup_retention_days    = 7

# Features
enable_global_accelerator = false  # Not needed for single region
enable_transit_gateway    = false  # Not needed for single region
enable_privatelink        = true

# Auto-scaling
autoscaling_min_instances = 1
autoscaling_max_instances = 5
autoscaling_target_rps    = 12.5

# Tags
tags = {
  Project     = "MRGC"
  Environment = "production"
  ManagedBy   = "terraform"
  Owner       = "$(whoami)"
  CostCenter  = "R&D"
}
EOF
```

#### Option B: Production (3 regions, 2 instances each) - ~$240/day

```bash
cat > terraform.tfvars <<EOF
# Basic Configuration
cluster_name = "mrgc"
environment  = "production"

# Regions (all 3)
regions = ["us-east-1", "us-east-2", "us-west-2"]

# Instance Configuration
gpu_instance_count      = 2  # Per region
gpu_instance_type       = "g6e.2xlarge"
gpu_instance_ami        = "ami-0c55b159cbfafe1f0"
gpu_instance_key_name   = "mrgc-keypair"

# Networking
vpc_cidr_base = "10.66.0.0/16"

# FSx Lustre
fsx_storage_capacity_gb      = 1200
fsx_per_unit_throughput      = 200
fsx_deployment_type          = "PERSISTENT_1"
fsx_backup_retention_days    = 7

# Features
enable_global_accelerator = true
enable_transit_gateway    = true
enable_privatelink        = true

# Auto-scaling
autoscaling_min_instances = 2  # Per region
autoscaling_max_instances = 10
autoscaling_target_rps    = 12.5

# Tags
tags = {
  Project     = "MRGC"
  Environment = "production"
  ManagedBy   = "terraform"
  Owner       = "$(whoami)"
  CostCenter  = "R&D"
}
EOF
```

**💰 Cost Warning:**
- **Option A:** ~$40/day (~$1,200/month)
- **Option B:** ~$240/day (~$7,200/month)

### 1.4 Review Configuration

```bash
cat terraform.tfvars
echo ""
echo "⚠️  Review the configuration above carefully!"
echo "⚠️  GPU instances are EXPENSIVE!"
read -p "Press Enter to continue or Ctrl+C to abort..."
```

---

## Step 2: Deploy Infrastructure (30-45 minutes)

### 2.1 Initialize Terraform

```bash
terraform init

# Should output:
# Terraform has been successfully initialized!
```

### 2.2 Plan Deployment

```bash
# See what will be created
terraform plan -out=tfplan

# Review the plan carefully
# Look for resource counts, estimated costs
```

### 2.3 Deploy Phase 1: Networking & State

Deploy foundational components first:

```bash
# Deploy VPC
terraform apply -target=module.vpc -auto-approve

# Deploy DynamoDB Global Tables
terraform apply -target=module.dynamodb -auto-approve

# Deploy Transit Gateway (if multi-region)
# terraform apply -target=module.transit_gateway -auto-approve

# Verify
aws ec2 describe-vpcs --filters "Name=tag:Name,Values=mrgc-vpc-*" --query 'Vpcs[].VpcId'
aws dynamodb list-tables | grep mrgc
```

**Checkpoint:** VPC and DynamoDB should be created. Estimated time: 5-10 minutes.

### 2.4 Deploy Phase 2: Storage

```bash
# Deploy FSx Lustre (takes 5-10 minutes)
terraform apply -target=module.fsx_lustre -auto-approve

# Wait for FSx to become available
aws fsx describe-file-systems \
  --query 'FileSystems[?Tags[?Key==`Project` && Value==`MRGC`]].{ID:FileSystemId,State:Lifecycle}' \
  --output table

# Should show: AVAILABLE
```

**Checkpoint:** FSx Lustre should be AVAILABLE. Estimated time: 10-15 minutes.

### 2.5 Deploy Phase 3: Load Balancing

```bash
# Deploy NLB
terraform apply -target=module.nlb -auto-approve

# Deploy Global Accelerator (if enabled)
# terraform apply -target=module.global_accelerator -auto-approve

# Get NLB DNS
aws elbv2 describe-load-balancers \
  --names mrgc-nlb-use1 \
  --query 'LoadBalancers[0].DNSName' \
  --output text
```

**Checkpoint:** NLB should be active. Estimated time: 3-5 minutes.

### 2.6 Deploy Phase 4: Complete Stack

```bash
# Deploy everything else
terraform apply -auto-approve

# This will create:
# - GPU instances
# - Security groups
# - IAM roles
# - ECS cluster for Regional Router
# - Auto-scaling configuration
```

**Checkpoint:** All resources created. Estimated time: 10-15 minutes.

### 2.7 Save Important Outputs

```bash
# Save all outputs to file
terraform output > ~/mrgc-outputs.txt

# Display key information
echo "=== MRGC Deployment Complete ==="
echo ""
echo "NLB DNS: $(terraform output -raw nlb_dns_name)"
echo "FSx DNS: $(terraform output -raw fsx_dns_name)"
echo "GPU Instance IPs: $(terraform output -raw gpu_instance_ips)"
echo ""
echo "Full outputs saved to: ~/mrgc-outputs.txt"
```

---

## Step 3: Configure GPU Instances (20-30 minutes per instance)

### 3.1 Get GPU Instance IPs

```bash
# Get instance IPs
GPU_IPS=$(terraform output -json gpu_instance_ips | jq -r '.[]')

# For single instance:
GPU_IP=$(echo "$GPU_IPS" | head -1)
echo "GPU Instance IP: ${GPU_IP}"
```

### 3.2 Connect to First GPU Instance

```bash
# SSH to GPU instance
ssh -i ~/.ssh/mrgc-keypair.pem ec2-user@${GPU_IP}
```

### 3.3 Install Dependencies (on GPU instance)

```bash
# Update system
sudo yum update -y

# Install Python 3.11
sudo yum install -y python3.11 python3.11-pip git

# Install Docker
sudo yum install -y docker
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -a -G docker ec2-user

# Install NVIDIA driver
sudo yum install -y kernel-devel-$(uname -r) kernel-headers-$(uname -r)
aws s3 cp --recursive s3://ec2-linux-nvidia-drivers/latest/ .
chmod +x NVIDIA-Linux-x86_64*.run
sudo ./NVIDIA-Linux-x86_64*.run --silent

# Verify GPU
nvidia-smi
# Should show: Tesla L40S GPU

# Install Lustre client
sudo amazon-linux-extras install -y lustre

# Install Nitro Enclaves CLI
sudo amazon-linux-extras install -y aws-nitro-enclaves-cli
sudo yum install -y aws-nitro-enclaves-cli-devel

# Allocate resources for enclave
sudo systemctl start nitro-enclaves-allocator.service
sudo systemctl enable nitro-enclaves-allocator.service
```

### 3.4 Mount FSx Lustre

```bash
# Get FSx DNS (from local machine)
FSX_DNS=$(terraform output -raw fsx_dns_name)
echo "FSx DNS: ${FSX_DNS}"

# Mount FSx (on GPU instance)
sudo mkdir -p /fsx
sudo mount -t lustre ${FSX_DNS}@tcp:/fsx /fsx

# Add to fstab for auto-mount
echo "${FSX_DNS}@tcp:/fsx /fsx lustre defaults,_netdev 0 0" | sudo tee -a /etc/fstab

# Verify mount
df -h | grep fsx
```

### 3.5 Clone Repository and Setup

```bash
# Clone repo (on GPU instance)
cd /home/ec2-user
git clone https://github.com/jbwitnessAI/mrgc.git
cd mrgc
```

### 3.6 Build and Run Nitro Enclave

```bash
cd applications/nitro-enclave

# Install dependencies
pip3.11 install -r requirements.txt

# Build enclave
./build.sh

# This creates: mrgc-enclave.eif
# Save the PCR values shown for KMS key policies

# Run enclave
sudo nitro-cli run-enclave \
  --eif-path mrgc-enclave.eif \
  --memory 4096 \
  --cpu-count 2 \
  --debug-mode

# Verify enclave running
sudo nitro-cli describe-enclaves
# Should show: State: RUNNING

# View enclave logs (optional)
ENCLAVE_ID=$(sudo nitro-cli describe-enclaves | jq -r '.[0].EnclaveID')
sudo nitro-cli console --enclave-id ${ENCLAVE_ID}
```

### 3.7 Start Parent Instance Application

```bash
cd /home/ec2-user/mrgc/applications/parent-instance

# Install dependencies
pip3.11 install -r requirements.txt

# Install PyTorch with CUDA (for GPU inference)
pip3.11 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Start parent app
nohup python3.11 parent_app.py > /var/log/parent-app.log 2>&1 &

# Check it started
sleep 5
curl http://localhost:8080/health
# Should return: {"status": "healthy", ...}

# Check logs
tail -f /var/log/parent-app.log
```

### 3.8 Repeat for All GPU Instances

```bash
# Exit GPU instance
exit

# For each GPU instance, repeat steps 3.2-3.7
for GPU_IP in $GPU_IPS; do
  echo "Configuring ${GPU_IP}..."
  # SSH and run setup commands
done
```

---

## Step 4: Deploy Regional Router (15 minutes)

### 4.1 Build and Push Docker Image

```bash
# From local machine
cd /Users/johnbutler/claude/mrgc/applications/regional-router

# Create ECR repository
aws ecr create-repository \
  --repository-name mrgc-regional-router \
  --region us-east-1

# Get ECR login
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com

# Build image
docker build -t mrgc-regional-router .

# Tag and push
docker tag mrgc-regional-router:latest \
  ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/mrgc-regional-router:latest

docker push ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/mrgc-regional-router:latest
```

### 4.2 Deploy to ECS

```bash
# Create ECS task definition
cat > task-definition.json <<EOF
{
  "family": "mrgc-regional-router",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "containerDefinitions": [{
    "name": "regional-router",
    "image": "${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/mrgc-regional-router:latest",
    "portMappings": [{
      "containerPort": 8080,
      "protocol": "tcp"
    }],
    "environment": [
      {"name": "AWS_REGION", "value": "us-east-1"}
    ],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/ecs/mrgc-regional-router",
        "awslogs-region": "us-east-1",
        "awslogs-stream-prefix": "router"
      }
    }
  }]
}
EOF

# Register task definition
aws ecs register-task-definition \
  --cli-input-json file://task-definition.json \
  --region us-east-1

# Create ECS service
aws ecs create-service \
  --cluster mrgc-cluster \
  --service-name regional-router \
  --task-definition mrgc-regional-router \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx,subnet-yyy],securityGroups=[sg-zzz],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:...,containerName=regional-router,containerPort=8080" \
  --region us-east-1
```

---

## Step 5: Upload Models to FSx (30-60 minutes)

### 5.1 Prepare Model Files

```bash
# Download or prepare your model
# Example: Llama 2 7B
# Place in: /local/models/llama-2-7b/

# Verify model has required files
ls /local/models/llama-2-7b/
# Should have: config.json, pytorch_model.bin, tokenizer files
```

### 5.2 Upload to S3

```bash
# Create S3 bucket for models
S3_BUCKET="mrgc-models-${AWS_ACCOUNT_ID}"
aws s3 mb s3://${S3_BUCKET} --region us-east-1

# Upload model
aws s3 sync /local/models/llama-2-7b/ s3://${S3_BUCKET}/model-a/ --region us-east-1

# This may take 10-30 minutes depending on model size
```

### 5.3 Import to FSx

```bash
# Get FSx ID
FSX_ID=$(terraform output -raw fsx_id)

# Trigger FSx import
aws fsx create-data-repository-task \
  --file-system-id ${FSX_ID} \
  --type IMPORT_METADATA_FROM_REPOSITORY \
  --paths /model-a/ \
  --region us-east-1

# Monitor import
aws fsx describe-data-repository-tasks \
  --filters Name=file-system-id,Values=${FSX_ID} \
  --region us-east-1
```

### 5.4 Create Model Registry

```bash
# SSH to any GPU instance
ssh -i ~/.ssh/mrgc-keypair.pem ec2-user@${GPU_IP}

# Create registry entry
cd /home/ec2-user/mrgc/scripts/model-management
python3 manage-model-registry.py add \
  --model-pool model-a \
  --name "Llama 2 7B" \
  --path /fsx/models/model-a \
  --size-gb 13.5 \
  --preload \
  --s3-source s3://${S3_BUCKET}/model-a/

# Verify
python3 manage-model-registry.py list
```

---

## Step 6: Test Deployment (15 minutes)

### 6.1 Test Health Endpoints

```bash
# Get NLB DNS
NLB_DNS=$(terraform output -raw nlb_dns_name)

# Test health
curl http://${NLB_DNS}:8080/health
# Should return: {"status": "healthy", "region": "us-east-1", ...}

# Test metrics
curl http://${NLB_DNS}:8080/metrics
# Should return instance metrics
```

### 6.2 Test End-to-End Inference

```bash
cd /Users/johnbutler/claude/mrgc

# Create test script
cat > test-inference.py <<'EOF'
import boto3
import json
import requests
import sys

# Configuration
nlb_dns = sys.argv[1] if len(sys.argv) > 1 else "your-nlb-dns"
region = "us-east-1"

# Create KMS key for testing
print("Creating test KMS key...")
kms = boto3.client('kms', region_name=region)
key_response = kms.create_key(Description='MRGC test key')
key_arn = key_response['KeyMetadata']['Arn']
print(f"Key ARN: {key_arn}")

try:
    # Prepare request
    payload = {
        "prompt": "Hello! Tell me about GPU computing.",
        "max_tokens": 100
    }

    # Encrypt with KMS
    print("Encrypting payload...")
    encrypted = kms.encrypt(
        KeyId=key_arn,
        Plaintext=json.dumps(payload).encode()
    )['CiphertextBlob']

    # Send to cluster
    print(f"Sending request to {nlb_dns}...")
    response = requests.post(
        f'http://{nlb_dns}:8080/inference',
        data=encrypted,
        headers={
            'X-KMS-Key-ARN': key_arn,
            'X-Tenant-ID': 'test-tenant',
            'X-Model-Pool': 'model-a',
            'X-Request-ID': 'test-001'
        },
        timeout=60
    )

    print(f"Response status: {response.status_code}")

    if response.status_code == 200:
        # Decrypt response
        print("Decrypting response...")
        decrypted = kms.decrypt(CiphertextBlob=response.content)['Plaintext']
        result = json.loads(decrypted)

        print("\n=== SUCCESS ===")
        print(f"Result: {json.dumps(result, indent=2)}")
    else:
        print(f"Error: {response.text}")

finally:
    # Cleanup
    print("Cleaning up test key...")
    kms.schedule_key_deletion(KeyId=key_arn, PendingWindowInDays=7)

EOF

# Run test
python3 test-inference.py ${NLB_DNS}
```

### 6.3 Monitor Logs

```bash
# View Regional Router logs
aws logs tail /ecs/mrgc-regional-router --follow

# View DynamoDB metrics
aws dynamodb describe-table --table-name mrgc-gpu_instances --query 'Table.ItemCount'

# View CloudWatch metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/NetworkELB \
  --metric-name ActiveFlowCount \
  --dimensions Name=LoadBalancer,Value=net/mrgc-nlb-use1/xxx \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average \
  --region us-east-1
```

---

## Step 7: Production Checklist

Before going to production:

### Security
- [ ] Review IAM roles and policies
- [ ] Configure KMS key policies with PCR values
- [ ] Set up VPC Flow Logs
- [ ] Enable GuardDuty
- [ ] Configure AWS Config rules
- [ ] Set up CloudTrail logging

### Monitoring
- [ ] Create CloudWatch dashboards
- [ ] Set up critical alarms (instance health, errors)
- [ ] Configure SNS notifications
- [ ] Set up log aggregation
- [ ] Enable X-Ray tracing

### Backup & DR
- [ ] Test FSx backups
- [ ] Document recovery procedures
- [ ] Test regional failover
- [ ] Set up cross-region replication for S3

### Cost Management
- [ ] Set up billing alerts
- [ ] Tag all resources properly
- [ ] Review and optimize instance types
- [ ] Consider Reserved Instances or Savings Plans

---

## Cleanup / Teardown

When you need to destroy everything:

```bash
cd /Users/johnbutler/claude/mrgc/infrastructure/terraform/environments/production

# Stop all GPU instances first (to save money while deciding)
terraform apply -target=module.gpu_instances -var gpu_instance_count=0

# Destroy everything
terraform destroy

# Verify
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Values=MRGC \
  --query 'ResourceTagMappingList[].ResourceARN'

# Clean up S3 buckets manually if needed
aws s3 rb s3://mrgc-models-${AWS_ACCOUNT_ID} --force
```

---

## Troubleshooting

### GPU instances not starting
```bash
# Check quotas
aws service-quotas get-service-quota --service-code ec2 --quota-code L-DB2E81BA

# Check for errors
aws ec2 describe-instances --filters "Name=tag:Project,Values=MRGC" | jq '.Reservations[].Instances[].StateReason'
```

### FSx mount fails
```bash
# Check security groups
aws fsx describe-file-systems --file-system-ids ${FSX_ID}

# Verify Lustre client installed
ssh ec2-user@${GPU_IP} "rpm -qa | grep lustre"
```

### Enclave won't start
```bash
# Check Nitro Enclaves enabled
aws ec2 describe-instances --instance-ids i-xxx --query 'Reservations[0].Instances[0].EnclaveOptions'

# Check memory allocation
ssh ec2-user@${GPU_IP} "cat /sys/module/nitro_enclaves/parameters/ne_cpus"
```

---

## Cost Monitoring

Set up billing alert:

```bash
aws sns create-topic --name mrgc-billing-alerts
aws sns subscribe --topic-arn arn:aws:sns:us-east-1:${AWS_ACCOUNT_ID}:mrgc-billing-alerts --protocol email --notification-endpoint your-email@example.com

# Create billing alarm
aws cloudwatch put-metric-alarm \
  --alarm-name mrgc-daily-cost-alert \
  --alarm-description "Alert when MRGC daily cost exceeds $50" \
  --metric-name EstimatedCharges \
  --namespace AWS/Billing \
  --statistic Maximum \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 50 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions arn:aws:sns:us-east-1:${AWS_ACCOUNT_ID}:mrgc-billing-alerts
```

---

## Next Steps

1. Load test with realistic traffic
2. Fine-tune auto-scaling parameters
3. Optimize GPU memory usage
4. Set up multi-region replication
5. Configure production monitoring
6. Document operational procedures

**Your MRGC cluster is now deployed!** 🎉

For support, check:
- CloudWatch Logs: `/aws/ec2/`, `/ecs/mrgc-regional-router`
- Terraform state: `terraform show`
- Application logs on GPU instances: `/var/log/parent-app.log`

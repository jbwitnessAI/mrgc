# Quick Start Guide

Get up and running with MRGC in 30 minutes.

## Prerequisites (5 minutes)

```bash
# 1. Install tools
brew install awscli terraform docker  # macOS
# or: sudo apt-get install awscli terraform docker  # Linux

# 2. Configure AWS
aws configure
# Enter your credentials

# 3. Verify access
aws sts get-caller-identity
# Should show your account

# 4. Clone repository (if not already)
cd /Users/johnbutler/claude/mrgc
```

## Option 1: Test Locally (No Cost)

Perfect for validating the code without AWS charges.

```bash
# 1. Create Python virtual environment
python3.11 -m venv venv
source venv/bin/activate

# 2. Test DynamoDB state manager
cd applications/global-state
pip install -r requirements.txt
python3 <<EOF
from state_manager import StateManager
mgr = StateManager(region='us-east-1')
print("✓ State manager works!")
EOF

# 3. Test Car Wash
cd ../car-wash
pip install -r requirements.txt
python carwash.py
# Should show cleanup report

# 4. Validate Terraform
cd ../../infrastructure/terraform/environments/production
terraform init
terraform validate
# Should output: Success!
```

**Result:** Confirms code works without AWS deployment.

---

## Option 2: Deploy Single Component (~$5, 1 hour)

Deploy just DynamoDB to test AWS integration.

```bash
cd infrastructure/terraform/environments/production

# 1. Create configuration
cat > terraform.tfvars <<EOF
cluster_name = "mrgc-test"
environment  = "dev"
regions      = ["us-east-1"]
vpc_cidr_base = "10.66.0.0/16"

tags = {
  Project = "MRGC"
  Environment = "dev"
}
EOF

# 2. Initialize Terraform
terraform init

# 3. Deploy DynamoDB only
terraform plan -target=module.dynamodb
terraform apply -target=module.dynamodb
# Type 'yes' when prompted

# 4. Verify tables created
aws dynamodb list-tables | grep mrgc

# 5. Test with Python
cd ../../applications/global-state
export AWS_REGION=us-east-1
python3 <<EOF
from state_manager import StateManager

mgr = StateManager(region='us-east-1')
mgr.register_gpu_instance(
    instance_id='i-test001',
    region='us-east-1',
    availability_zone='us-east-1a',
    private_ip='10.66.1.10',
    instance_type='g6e.2xlarge'
)

instances = mgr.list_gpu_instances()
print(f"✓ Registered {len(instances)} instance(s)")

mgr.delete_gpu_instance('i-test001')
EOF

# 6. Cleanup
cd ../../infrastructure/terraform/environments/production
terraform destroy -target=module.dynamodb
```

**Cost:** ~$5 for 1 hour of DynamoDB

**Result:** Confirms AWS integration works.

---

## Option 3: Deploy Single Region Stack (~$10, 4 hours)

Deploy minimal working cluster in one region.

```bash
cd infrastructure/terraform/environments/production

# 1. Update configuration
cat > terraform.tfvars <<EOF
cluster_name = "mrgc-test"
environment  = "dev"
regions      = ["us-east-1"]

# Minimal setup
gpu_instance_count = 1
gpu_instance_type  = "g6e.2xlarge"
fsx_storage_capacity_gb = 1200

vpc_cidr_base = "10.66.0.0/16"

tags = {
  Project = "MRGC"
  Environment = "dev"
}
EOF

# 2. Deploy infrastructure
terraform init
terraform apply
# This takes 15-20 minutes
# Type 'yes' when prompted

# 3. Get outputs
NLB_DNS=$(terraform output -raw nlb_dns_name)
FSX_DNS=$(terraform output -raw fsx_dns_name)
GPU_IP=$(terraform output -raw gpu_instance_ip)

echo "NLB: ${NLB_DNS}"
echo "FSx: ${FSX_DNS}"
echo "GPU: ${GPU_IP}"

# 4. SSH to GPU instance and set up
ssh ec2-user@${GPU_IP}

# On GPU instance:
# Install Lustre client
sudo amazon-linux-extras install -y lustre

# Mount FSx
sudo mkdir -p /fsx
sudo mount -t lustre ${FSX_DNS}@tcp:/fsx /fsx

# Clone repo
git clone https://github.com/jbwitnessAI/mrgc.git
cd mrgc

# Install parent app
cd applications/parent-instance
pip3 install -r requirements.txt

# Note: GPU inference requires CUDA/PyTorch
# For testing, the mock mode will work

# 5. Test health endpoint (from your local machine)
curl http://${NLB_DNS}:8080/health
# Should return JSON with health status

# 6. Cleanup when done
terraform destroy
```

**Cost:** ~$10 for 4 hours (1 GPU instance + FSx)

**Result:** Working single-region cluster.

---

## Option 4: Full Multi-Region Deployment (~$40, 8 hours)

Deploy production-like setup across 3 regions.

```bash
# Update terraform.tfvars
cat > terraform.tfvars <<EOF
cluster_name = "mrgc-prod"
environment  = "production"
regions      = ["us-east-1", "us-east-2", "us-west-2"]

gpu_instance_count = 2  # Per region, 6 total
gpu_instance_type  = "g6e.2xlarge"
fsx_storage_capacity_gb = 1200

vpc_cidr_base = "10.66.0.0/16"

# Enable all features
enable_global_accelerator = true
enable_transit_gateway    = true
enable_privatelink        = true

tags = {
  Project = "MRGC"
  Environment = "production"
}
EOF

# Deploy
terraform apply
# Takes 30-40 minutes

# Test Global Accelerator
GA_IP=$(terraform output -raw global_accelerator_ip)
curl http://${GA_IP}:8080/health
```

**Cost:** ~$40 for 8 hours (6 GPU instances + full infrastructure)

**Result:** Production-ready multi-region cluster.

---

## Recommended Path

For first-time users, follow this progression:

1. ✅ **Start:** Option 1 (Local Testing) - Validate code works
2. ✅ **Next:** Option 2 (Single Component) - Confirm AWS integration
3. ✅ **Then:** Option 3 (Single Region) - Test end-to-end flow
4. ✅ **Finally:** Option 4 (Multi-Region) - Production deployment

**Total learning path:** ~$55 in AWS costs over 1-2 days

---

## What to Test

After deployment, test these key features:

### 1. State Management
```bash
python applications/global-state/state_manager.py
```

### 2. Health Checks
```bash
curl http://<nlb-dns>:8080/health
```

### 3. Routing
```bash
# Send test request to Regional Router
curl -X POST http://<nlb-dns>:8080/inference \
  -H "X-Tenant-ID: test" \
  -H "X-Model-Pool: model-a"
```

### 4. Failover (Multi-Region)
```bash
# Stop instances in one region
aws ec2 stop-instances --instance-ids <ids> --region us-east-1

# Traffic should automatically route to healthy regions
```

### 5. Auto-Scaling
```bash
# Generate load and watch instance count change
# Should scale up when RPS > 15 per instance
```

---

## Important Notes

⚠️ **GPU Instance Costs:** g6e.2xlarge costs ~$1.60/hour (~$1,200/month)

⚠️ **Stop Instances When Not Testing:**
```bash
# Stop all GPU instances to save money
aws ec2 stop-instances --instance-ids $(aws ec2 describe-instances \
  --filters "Name=tag:Project,Values=MRGC" "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].InstanceId' --output text)
```

⚠️ **Always Cleanup:**
```bash
terraform destroy
# Verify everything deleted
```

✅ **Use Spot Instances for Testing:** 70% cheaper than on-demand

---

## Next Steps

After completing quick start:

1. Read `docs/BUILD_AND_TEST.md` for comprehensive testing
2. Review `PROJECT_SUMMARY.md` for architecture details
3. Check component READMEs in `applications/*/README.md`
4. Set up monitoring with CloudWatch dashboards
5. Configure production security (IAM, KMS policies)

---

## Getting Help

**Stuck?** Check:
- `docs/BUILD_AND_TEST.md` - Detailed testing guide
- Application READMEs - Component-specific docs
- Terraform outputs - Resource identifiers
- CloudWatch Logs - Application logs

**Still stuck?** Review:
- AWS CloudFormation console for stack errors
- Terraform state: `terraform show`
- Security groups: Ensure ports are open
- IAM roles: Verify permissions

Good luck! 🚀

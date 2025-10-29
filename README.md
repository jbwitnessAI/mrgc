# Multi-Region Super GPU Cluster

A highly secure, globally distributed GPU inference cluster spanning 3 AWS regions with bank-grade security using AWS Nitro Enclaves.

## Overview

This system provides:
- **Single logical cluster** spanning US-East-1, US-East-2, and US-West-2
- **Private global endpoint** with intelligent routing
- **AWS Nitro Enclave security** for per-tenant encryption
- **Fast model loading** (30-45 seconds) with FSx Lustre
- **Intelligent routing** based on least-connections + lowest-latency
- **Auto-scaling** based on requests per second
- **Automatic failover** for disaster recovery

## Quick Stats

| Metric | Baseline (50 instances) | Peak (150 instances) |
|--------|-------------------------|----------------------|
| **RPS Capacity** | 50-75 RPS | 150-225 RPS |
| **Concurrent Users** | 1,500-2,250 | 4,500-6,750 |
| **Monthly Cost** | $35K | $85K |
| **Model Loading** | 30-45 seconds | 30-45 seconds |
| **Availability** | 99.99% | 99.99% |

## Architecture
```
Tenant VPCs
    ↓
AWS Global Accelerator (Anycast IPs)
    ↓
Regional NLB (us-east-1, us-east-2, us-west-2)
    ↓
Regional Router (ECS Fargate)
    ↓
g6e.2xlarge GPU Instances with Nitro Enclaves
    ↓
FSx Lustre (per region)
```

## Key Components

1. **Nitro Enclave**: Handles all encryption/decryption with cryptographic attestation
2. **Parent Instance**: Runs GPU inference on g6e.2xlarge (NVIDIA L40S)
3. **Regional Router**: Intelligent request routing with failover
4. **Global State**: DynamoDB Global Tables for cluster coordination
5. **Auto-scaler**: Lifecycle management with security validation

## Security Features

- ✅ **Hardware-enforced isolation** via Nitro Enclaves
- ✅ **Per-tenant encryption** with dynamic KMS keys
- ✅ **Cryptographic attestation** of enclave code
- ✅ **Secure cleanup validation** before instance reuse
- ✅ **Zero-trust architecture** (even AWS can't access tenant data)

## Getting Started

### Prerequisites

- AWS Account with appropriate permissions
- Terraform >= 1.5.0
- Docker >= 20.10
- Python >= 3.11
- AWS Nitro CLI

### Quick Deploy
```bash
# 1. Clone repository
git clone <repo-url>
cd multi-region-gpu-cluster

# 2. Configure AWS credentials
export AWS_PROFILE=your-profile

# 3. Initialize Terraform
cd infrastructure/terraform/environments/production
terraform init

# 4. Review and apply
terraform plan
terraform apply

# 5. Deploy applications
cd ../../../../scripts/setup
./01-setup-networking.sh
./02-deploy-fsx.sh
./03-setup-dynamodb.sh
./04-deploy-accelerator.sh
./05-initial-capacity.sh
```

### Deployment Timeline

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| Infrastructure | 2 weeks | VPC, FSx, networking |
| Applications | 4 weeks | Nitro enclave, parent app, router |
| Integration | 3 weeks | End-to-end testing |
| Security Validation | 2 weeks | Penetration testing, compliance |
| Production Deploy | 1 week | Go-live |
| **Total** | **12 weeks** | **Production-ready system** |

## Documentation

- [Architecture Details](./ARCHITECTURE.md)
- [Requirements Specification](./REQUIREMENTS.md)
- [Implementation Plan](./IMPLEMENTATION_PLAN.md)
- [Cost Analysis](./COST_ANALYSIS.md)
- [Security Documentation](./SECURITY.md)
- [API Documentation](./docs/api/)
- [Runbooks](./docs/runbooks/)

## Monitoring

Access dashboards at:
- CloudWatch: `https://console.aws.amazon.com/cloudwatch/`
- Grafana: `https://grafana.your-domain.com`

Key metrics:
- `gpu_cluster/rps` - Requests per second
- `gpu_cluster/queue_depth` - Queue depth per instance
- `gpu_cluster/model_load_time` - Model loading time
- `gpu_cluster/inference_latency` - Inference latency P50/P95/P99

## Runbooks

- [Scaling Up/Down](./docs/runbooks/scaling.md)
- [Handling Regional Failures](./docs/runbooks/incident-response.md)
- [Deploying Model Updates](./docs/runbooks/maintenance.md)

## Testing
```bash
# Unit tests
pytest tests/unit/

# Integration tests
pytest tests/integration/

# Load testing
python scripts/testing/load-test.py --rps 100 --duration 300

# Security audit
python scripts/testing/security-audit.py
```

## Cost Optimization

- Use **70% reserved instances** for baseline capacity
- Use **30% on-demand** for burst capacity
- Enable **auto-scaling** to match demand
- **Estimated savings**: 40-50% vs all on-demand

## Support

- **Documentation**: See `docs/` directory
- **Issues**: Create GitHub issue
- **Emergency**: PagerDuty integration configured

## License

[Your License]

## Contributors

[Your Team]

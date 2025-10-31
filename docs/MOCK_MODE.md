# Mock Mode Support

## Current Status: ⚠️ Partial Mock Support

The MRGC codebase has **partial mock mode** built-in. Some components work locally without AWS, others require AWS services.

## What Works Out of the Box (No AWS Required)

### ✅ GPU Inference Engine
**File:** `applications/parent-instance/gpu_inference.py`

```python
# Line 227 - Mock mode built-in
result = f"[MOCK GPU INFERENCE]\nPrompt: {prompt[:100]}...\n"
```

**Test:**
```bash
cd applications/parent-instance
python3 <<EOF
from gpu_inference import GPUInferenceEngine
from model_loader import ModelLoader

class MockModelLoader:
    def get_model(self, pool): return {"loaded": True}

engine = GPUInferenceEngine(model_loader=MockModelLoader())
engine.gpu_available = True
engine.initialized = True

result = engine.run_inference(
    prompt="Test", model_pool="model-a", request_id="test-001"
)
print(result)  # Returns mock inference result
EOF
```

**Result:** ✅ Works without AWS

---

### ✅ Nitro Enclave Attestation
**File:** `applications/nitro-enclave/attestation.py`

```python
# Line 65 - Mock attestation generation
def _generate_mock_attestation(self, ...):
    logger.warning("Generating MOCK attestation document")
    # Returns mock attestation with fake PCR values
```

**Test:**
```bash
cd applications/nitro-enclave
python3 <<EOF
from attestation import AttestationManager

mgr = AttestationManager()
attestation = mgr.generate_attestation()
print(f"Generated: {len(attestation)} bytes")

is_valid = mgr.verify_attestation(attestation)
print(f"Valid: {is_valid}")
EOF
```

**Result:** ✅ Works without AWS

---

### ⚠️ Car Wash (Mostly Works)
**File:** `applications/car-wash/carwash.py`

Most cleanup steps are mocked, but health validation tries to run `nvidia-smi`.

**Test:**
```bash
cd applications/car-wash
python3 <<EOF
from carwash import CarWash

carwash = CarWash()
success, report = carwash.run_cleanup("test-001")
print(f"Success: {success}")
print(f"Steps: {report['steps']}")
EOF
```

**Result:** ⚠️ Mostly works, fails on GPU health check

---

## What Requires AWS

### ❌ State Manager (DynamoDB)
**File:** `applications/global-state/state_manager.py`

```python
# Requires real DynamoDB
self.dynamodb = boto3.resource('dynamodb', region_name=region)
```

**Why it fails:**
- No mock DynamoDB implementation
- Requires AWS credentials
- Needs actual DynamoDB tables

---

### ❌ KMS Handler
**File:** `applications/nitro-enclave/kms_handler.py`

```python
# Requires real AWS KMS
self.kms_client = boto3.client('kms')
```

**Why it fails:**
- No mock KMS
- Real encryption/decryption needed
- Requires AWS credentials

---

### ❌ Regional Router
**File:** `applications/regional-router/router_app.py`

```python
# Requires DynamoDB for instance lookup
self.registry = InstanceRegistry(region=region)
```

**Why it fails:**
- Depends on State Manager (DynamoDB)
- Needs instance registry data

---

## Summary Table

| Component | Mock Support | Requires AWS | Can Run Locally |
|-----------|--------------|--------------|-----------------|
| GPU Inference | ✅ Yes | No | ✅ Yes |
| Nitro Attestation | ✅ Yes | No | ✅ Yes |
| Car Wash | ⚠️ Partial | No | ⚠️ Mostly |
| Model Loader | ⚠️ Partial | Needs local `/fsx` | ⚠️ With setup |
| State Manager | ❌ No | DynamoDB | ❌ No |
| KMS Handler | ❌ No | AWS KMS | ❌ No |
| Regional Router | ❌ No | DynamoDB | ❌ No |
| Auto-scaler | ❌ No | EC2, CloudWatch, DynamoDB | ❌ No |
| Failover Handler | ❌ No | Global Accelerator, DynamoDB | ❌ No |

---

## Option 1: Test What Works Now

```bash
# Run the test script
./test-local-mock.sh

# What you'll see:
# ✅ GPU Inference - WORKS
# ✅ Nitro Attestation - WORKS
# ⚠️ Car Wash - MOSTLY WORKS
# ❌ State Manager - NEEDS AWS
# ❌ KMS Handler - NEEDS AWS
# ❌ Others - NEED AWS
```

---

## Option 2: Add Full Mock Mode

I can create a **complete mock layer** that simulates all AWS services locally. This would include:

### Mock DynamoDB
```python
class MockDynamoDB:
    """In-memory DynamoDB for testing"""
    def __init__(self):
        self.tables = {
            'gpu_instances': {},
            'routing_state': {},
            'autoscaling_state': {},
            'cleanup_validation': {},
            'metrics': {}
        }
```

### Mock KMS
```python
class MockKMS:
    """Local encryption for testing"""
    def encrypt(self, plaintext):
        # Simple base64 "encryption"
        return base64.b64encode(plaintext)

    def decrypt(self, ciphertext):
        return base64.b64decode(ciphertext)
```

### Mock AWS Services
- Mock EC2 (for auto-scaling)
- Mock CloudWatch (for metrics)
- Mock Global Accelerator (for failover)

**Cost:** Free (all local)
**Time to implement:** 2-3 hours
**Benefit:** Full local testing without AWS

---

## Option 3: Use LocalStack

[LocalStack](https://localstack.cloud/) provides local AWS service emulation:

```bash
# Install LocalStack
pip install localstack

# Start services
localstack start

# Configure boto3 to use LocalStack
export AWS_ENDPOINT_URL=http://localhost:4566
```

**Pros:**
- Industry-standard tool
- Supports most AWS services
- Free tier available

**Cons:**
- Complex setup
- Some services incomplete
- Requires Docker

---

## Option 4: Minimal AWS Deployment

Deploy only the essential AWS services for testing:

```bash
# Deploy just DynamoDB (cheapest AWS option)
terraform apply -target=module.dynamodb

# Cost: ~$2/day for DynamoDB only
```

Then test locally with real DynamoDB but mock everything else.

---

## Recommendation

For your use case, I recommend:

### Phase 1: Test What Works Now (Free)
```bash
./test-local-mock.sh
```
Tests GPU inference, attestation, car wash without AWS.

### Phase 2: Choose Your Path

**Option A: Full Mock Mode (Free, 2-3 hours setup)**
- I create complete mock layer
- Everything runs locally
- Good for development/testing
- Not production-ready

**Option B: LocalStack (Free, 4-6 hours setup)**
- Use industry-standard tool
- More realistic AWS emulation
- Steeper learning curve

**Option C: Minimal AWS ($2-10/day)**
- Deploy only DynamoDB + FSx
- Most realistic testing
- Small AWS cost

**Option D: Full AWS ($40-240/day)**
- Deploy everything
- Production-ready testing
- High cost

---

## Quick Decision Matrix

| Your Goal | Recommended Option | Cost | Setup Time |
|-----------|-------------------|------|------------|
| **Validate code syntax** | Test what works now | $0 | 5 min |
| **Test individual components** | Full Mock Mode | $0 | 2-3 hours |
| **Test integration** | Minimal AWS | $2-10/day | 1 hour |
| **Production validation** | Full AWS | $40+/day | 2-3 hours |

---

## Want Me to Create Full Mock Mode?

I can add complete mock implementations for:

1. **MockStateManager** - In-memory DynamoDB
2. **MockKMSHandler** - Local encryption
3. **MockEC2** - Fake instance management
4. **MockCloudWatch** - Local metrics
5. **MockGlobalAccelerator** - Simulated failover

This would let you run **everything locally for free**.

Would you like me to:
- ✅ Create full mock mode?
- ✅ Set up LocalStack integration?
- ✅ Create minimal AWS deployment guide?

Let me know! 🚀

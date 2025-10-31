#!/bin/bash
#
# Test Local Mock Mode
#
# This tests which components work without AWS

set -e

echo "=========================================="
echo "Testing MRGC Local Mock Mode"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo ""
echo "=========================================="
echo "Test 1: GPU Inference (Mock Mode)"
echo "=========================================="
cd applications/parent-instance
pip install -q -r requirements.txt 2>/dev/null || true

python3 <<'EOF'
import sys
sys.path.insert(0, '.')

from gpu_inference import GPUInferenceEngine
from model_loader import ModelLoader

# Mock model loader
class MockModelLoader:
    def get_model(self, model_pool):
        return {"model_pool": model_pool, "loaded": True}

loader = MockModelLoader()
engine = GPUInferenceEngine(model_loader=loader)

# Mock GPU available
engine.gpu_available = True
engine.initialized = True

# Run mock inference
result = engine.run_inference(
    prompt="Hello, world!",
    model_pool="model-a",
    max_tokens=50,
    request_id="test-001"
)

if result and "MOCK GPU INFERENCE" in result:
    print("\033[0;32m✓ GPU Inference Mock Mode WORKS\033[0m")
    print(f"Result: {result[:100]}...")
else:
    print("\033[0;31m✗ GPU Inference Mock Mode FAILED\033[0m")
    sys.exit(1)
EOF

cd ../..
echo ""

echo "=========================================="
echo "Test 2: Nitro Enclave Attestation (Mock)"
echo "=========================================="
cd applications/nitro-enclave
pip install -q -r requirements.txt 2>/dev/null || true

python3 <<'EOF'
from attestation import AttestationManager

manager = AttestationManager()
attestation = manager.generate_attestation()

if attestation and len(attestation) > 0:
    print("\033[0;32m✓ Attestation Mock Mode WORKS\033[0m")
    print(f"Attestation size: {len(attestation)} bytes")

    # Verify it
    is_valid = manager.verify_attestation(attestation)
    print(f"Verification: {'PASS' if is_valid else 'FAIL'}")
else:
    print("\033[0;31m✗ Attestation Mock Mode FAILED\033[0m")
    sys.exit(1)
EOF

cd ../..
echo ""

echo "=========================================="
echo "Test 3: Car Wash (Mock Mode)"
echo "=========================================="
cd applications/car-wash
pip install -q -r requirements.txt 2>/dev/null || true

python3 <<'EOF'
from carwash import CarWash

carwash = CarWash()
success, report = carwash.run_cleanup(request_id="test-001")

if success:
    print("\033[0;32m✓ Car Wash Mock Mode WORKS\033[0m")
    print(f"Cleanup time: {report['cleanup_time_seconds']:.2f}s")
    print(f"All steps passed: {all(report['steps'].values())}")
else:
    print("\033[0;31m✗ Car Wash Mock Mode FAILED\033[0m")
    sys.exit(1)
EOF

cd ../..
echo ""

echo "=========================================="
echo "Test 4: State Manager (Requires AWS)"
echo "=========================================="
cd applications/global-state

python3 <<'EOF' 2>&1 | head -5
from state_manager import StateManager

try:
    manager = StateManager(region='us-east-1')
    print("\033[1;33m⚠ State Manager requires AWS DynamoDB\033[0m")
    print("This test requires real AWS credentials")
except Exception as e:
    if "credentials" in str(e).lower() or "region" in str(e).lower():
        print("\033[1;33m⚠ State Manager requires AWS DynamoDB\033[0m")
        print(f"Error (expected): {str(e)[:100]}")
    else:
        print(f"\033[0;31m✗ Unexpected error: {e}\033[0m")
EOF

cd ../..
echo ""

echo "=========================================="
echo "Summary"
echo "=========================================="
echo ""
echo -e "${GREEN}✓ Components that work WITHOUT AWS:${NC}"
echo "  - GPU Inference (mock mode)"
echo "  - Nitro Enclave Attestation (mock mode)"
echo "  - Car Wash (mock mode)"
echo ""
echo -e "${YELLOW}⚠ Components that REQUIRE AWS:${NC}"
echo "  - State Manager (needs DynamoDB)"
echo "  - KMS Handler (needs AWS KMS)"
echo "  - Regional Router (needs DynamoDB)"
echo "  - Auto-scaler (needs EC2, CloudWatch, DynamoDB)"
echo "  - Failover Handler (needs Global Accelerator)"
echo ""
echo -e "${YELLOW}Recommendation:${NC}"
echo "For full local testing, use one of these approaches:"
echo "1. Deploy only infrastructure (no GPUs) to AWS: ~\$10/day"
echo "2. Use LocalStack to mock AWS services (free, complex setup)"
echo "3. Create a full mock layer (I can help with this)"
echo ""

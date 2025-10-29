#!/bin/bash
#
# Build Nitro Enclave Image
#
# This script:
# 1. Builds a Docker image with the enclave application
# 2. Converts it to an Enclave Image File (EIF) using nitro-cli
# 3. Outputs PCR values for KMS key policies
#
# Prerequisites:
# - Docker installed and running
# - nitro-cli installed (on parent EC2 instance)
# - Sufficient disk space (~2-3 GB for enclave image)

set -e

# Configuration
IMAGE_NAME="mrgc-enclave"
IMAGE_TAG="latest"
EIF_NAME="mrgc-enclave.eif"
ENCLAVE_MEMORY_MB=4096  # 4 GB RAM for enclave
ENCLAVE_VCPUS=2         # 2 vCPUs for enclave

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Building Nitro Enclave Image${NC}"
echo -e "${GREEN}================================${NC}"
echo ""

# Step 1: Build Docker image
echo -e "${YELLOW}[1/3] Building Docker image...${NC}"
docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .

if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to build Docker image${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Docker image built successfully${NC}"
echo ""

# Step 2: Convert to Enclave Image File (EIF)
echo -e "${YELLOW}[2/3] Converting to Enclave Image File (EIF)...${NC}"
echo "This may take a few minutes..."
echo ""

nitro-cli build-enclave \
    --docker-uri ${IMAGE_NAME}:${IMAGE_TAG} \
    --output-file ${EIF_NAME} > build-output.json

if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to build enclave image${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Enclave image built successfully${NC}"
echo ""

# Step 3: Extract and display PCR values
echo -e "${YELLOW}[3/3] Extracting PCR values...${NC}"
echo ""

# Parse PCR values from build output
PCR0=$(jq -r '.Measurements.PCR0' build-output.json)
PCR1=$(jq -r '.Measurements.PCR1' build-output.json)
PCR2=$(jq -r '.Measurements.PCR2' build-output.json)

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Build Complete!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Enclave Image File: ${EIF_NAME}"
echo "Size: $(du -h ${EIF_NAME} | cut -f1)"
echo ""
echo -e "${YELLOW}PCR Values (for KMS key policies):${NC}"
echo ""
echo "  PCR0 (Enclave Kernel):      ${PCR0}"
echo "  PCR1 (Enclave Initramfs):   ${PCR1}"
echo "  PCR2 (Enclave Application): ${PCR2}"
echo ""
echo -e "${YELLOW}KMS Key Policy Condition:${NC}"
echo ""
echo "Add this to tenant KMS key policies to allow decryption"
echo "ONLY from this verified enclave:"
echo ""
echo "\"Condition\": {"
echo "  \"StringEqualsIgnoreCase\": {"
echo "    \"kms:RecipientAttestation:ImageSha384\": \"${PCR2}\""
echo "  }"
echo "}"
echo ""

# Save PCR values to file for later reference
cat > pcr-values.json <<EOF
{
  "PCR0": "${PCR0}",
  "PCR1": "${PCR1}",
  "PCR2": "${PCR2}",
  "build_timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "image_name": "${IMAGE_NAME}:${IMAGE_TAG}",
  "eif_name": "${EIF_NAME}"
}
EOF

echo -e "${GREEN}PCR values saved to: pcr-values.json${NC}"
echo ""

# Display next steps
echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "1. Copy EIF to parent EC2 instances:"
echo "   scp ${EIF_NAME} ec2-user@<instance-ip>:/opt/mrgc/"
echo ""
echo "2. Update KMS key policies with PCR2 value above"
echo ""
echo "3. Run enclave on parent instance:"
echo "   nitro-cli run-enclave \\"
echo "     --eif-path /opt/mrgc/${EIF_NAME} \\"
echo "     --memory ${ENCLAVE_MEMORY_MB} \\"
echo "     --cpu-count ${ENCLAVE_VCPUS} \\"
echo "     --debug-mode"
echo ""
echo "4. Check enclave status:"
echo "   nitro-cli describe-enclaves"
echo ""
echo "5. View enclave logs:"
echo "   nitro-cli console --enclave-id <enclave-id>"
echo ""

echo -e "${GREEN}Build complete!${NC}"

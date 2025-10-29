#!/bin/bash
#
# Upload Model to FSx Lustre
#
# This script:
# 1. Uploads model files to S3
# 2. Triggers FSx import from S3
# 3. Waits for import to complete
# 4. Updates model registry
# 5. Verifies model is accessible

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../../config/fsx-lustre.yaml"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Parse arguments
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --model-path PATH         Local path to model files"
    echo "  --model-pool NAME         Model pool name (e.g., model-a)"
    echo "  --model-name NAME         Human-readable model name"
    echo "  --region REGION           AWS region (e.g., us-east-1)"
    echo "  --s3-bucket BUCKET        S3 bucket name"
    echo "  --fsx-id FSXID            FSx file system ID"
    echo "  --preload BOOL            Preload on instance startup (true/false)"
    echo "  --help                    Show this help message"
    echo ""
    echo "Example:"
    echo "  $0 --model-path /local/models/llama-2-7b \\"
    echo "     --model-pool model-a \\"
    echo "     --model-name \"Llama 2 7B\" \\"
    echo "     --region us-east-1 \\"
    echo "     --s3-bucket mrgc-models-use1 \\"
    echo "     --fsx-id fs-0123456789abcdef0 \\"
    echo "     --preload true"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --model-path)
            MODEL_PATH="$2"
            shift 2
            ;;
        --model-pool)
            MODEL_POOL="$2"
            shift 2
            ;;
        --model-name)
            MODEL_NAME="$2"
            shift 2
            ;;
        --region)
            REGION="$2"
            shift 2
            ;;
        --s3-bucket)
            S3_BUCKET="$2"
            shift 2
            ;;
        --fsx-id)
            FSX_ID="$2"
            shift 2
            ;;
        --preload)
            PRELOAD="$2"
            shift 2
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Validate required arguments
if [[ -z "$MODEL_PATH" || -z "$MODEL_POOL" || -z "$MODEL_NAME" || -z "$REGION" || -z "$S3_BUCKET" || -z "$FSX_ID" ]]; then
    echo -e "${RED}Error: Missing required arguments${NC}"
    usage
    exit 1
fi

# Set defaults
PRELOAD=${PRELOAD:-false}
S3_PREFIX="${MODEL_POOL}"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Uploading Model to FSx Lustre${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Model Path:  ${MODEL_PATH}"
echo "Model Pool:  ${MODEL_POOL}"
echo "Model Name:  ${MODEL_NAME}"
echo "Region:      ${REGION}"
echo "S3 Bucket:   s3://${S3_BUCKET}/${S3_PREFIX}/"
echo "FSx ID:      ${FSX_ID}"
echo "Preload:     ${PRELOAD}"
echo ""

# Step 1: Verify local model files
echo -e "${YELLOW}[1/6] Verifying local model files...${NC}"

if [[ ! -d "$MODEL_PATH" ]]; then
    echo -e "${RED}Error: Model path not found: ${MODEL_PATH}${NC}"
    exit 1
fi

# Check for required files
REQUIRED_FILES=("config.json")
for file in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "${MODEL_PATH}/${file}" ]]; then
        echo -e "${RED}Error: Required file not found: ${file}${NC}"
        exit 1
    fi
done

# Calculate model size
MODEL_SIZE_MB=$(du -sm "${MODEL_PATH}" | cut -f1)
MODEL_SIZE_GB=$(echo "scale=2; ${MODEL_SIZE_MB} / 1024" | bc)

echo -e "${GREEN}✓ Model files verified (${MODEL_SIZE_GB} GB)${NC}"
echo ""

# Step 2: Upload to S3
echo -e "${YELLOW}[2/6] Uploading model files to S3...${NC}"
echo "This may take several minutes..."
echo ""

aws s3 sync "${MODEL_PATH}" "s3://${S3_BUCKET}/${S3_PREFIX}/" \
    --region "${REGION}" \
    --no-progress

if [[ $? -ne 0 ]]; then
    echo -e "${RED}Error: Failed to upload to S3${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Uploaded to S3${NC}"
echo ""

# Step 3: Trigger FSx import from S3
echo -e "${YELLOW}[3/6] Triggering FSx import from S3...${NC}"

TASK_ID=$(aws fsx create-data-repository-task \
    --file-system-id "${FSX_ID}" \
    --type IMPORT_METADATA_FROM_REPOSITORY \
    --paths "/${S3_PREFIX}/" \
    --region "${REGION}" \
    --query 'DataRepositoryTask.TaskId' \
    --output text)

if [[ $? -ne 0 ]]; then
    echo -e "${RED}Error: Failed to trigger FSx import${NC}"
    exit 1
fi

echo "Task ID: ${TASK_ID}"
echo -e "${GREEN}✓ Import task started${NC}"
echo ""

# Step 4: Wait for import to complete
echo -e "${YELLOW}[4/6] Waiting for FSx import to complete...${NC}"
echo "This may take 1-2 minutes..."

MAX_WAIT=300  # 5 minutes
WAIT_TIME=0
SLEEP_INTERVAL=10

while [[ $WAIT_TIME -lt $MAX_WAIT ]]; do
    TASK_STATUS=$(aws fsx describe-data-repository-tasks \
        --task-ids "${TASK_ID}" \
        --region "${REGION}" \
        --query 'DataRepositoryTasks[0].Lifecycle' \
        --output text)

    if [[ "$TASK_STATUS" == "SUCCEEDED" ]]; then
        echo -e "${GREEN}✓ FSx import completed successfully${NC}"
        break
    elif [[ "$TASK_STATUS" == "FAILED" || "$TASK_STATUS" == "CANCELED" ]]; then
        echo -e "${RED}Error: FSx import failed with status: ${TASK_STATUS}${NC}"
        exit 1
    fi

    echo "  Status: ${TASK_STATUS} (waiting ${WAIT_TIME}s / ${MAX_WAIT}s)"
    sleep $SLEEP_INTERVAL
    WAIT_TIME=$((WAIT_TIME + SLEEP_INTERVAL))
done

if [[ $WAIT_TIME -ge $MAX_WAIT ]]; then
    echo -e "${RED}Error: FSx import timeout${NC}"
    exit 1
fi

echo ""

# Step 5: Update model registry
echo -e "${YELLOW}[5/6] Updating model registry...${NC}"

# Create registry entry
REGISTRY_ENTRY=$(cat <<EOF
{
  "model_pool": "${MODEL_POOL}",
  "name": "${MODEL_NAME}",
  "path": "/fsx/models/${MODEL_POOL}",
  "size_gb": ${MODEL_SIZE_GB},
  "preload": ${PRELOAD},
  "s3_source": "s3://${S3_BUCKET}/${S3_PREFIX}/",
  "uploaded_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "uploaded_by": "${USER}",
  "region": "${REGION}"
}
EOF
)

# Save to local file for reference
REGISTRY_FILE="${SCRIPT_DIR}/../../metadata/model-registry-${MODEL_POOL}.json"
mkdir -p "$(dirname "${REGISTRY_FILE}")"
echo "${REGISTRY_ENTRY}" > "${REGISTRY_FILE}"

echo -e "${GREEN}✓ Model registry updated${NC}"
echo "Registry entry saved to: ${REGISTRY_FILE}"
echo ""

# Step 6: Verify model is accessible
echo -e "${YELLOW}[6/6] Verification${NC}"
echo ""
echo -e "${GREEN}Model uploaded successfully!${NC}"
echo ""
echo "Next steps:"
echo ""
echo "1. Verify model on FSx (from any GPU instance):"
echo "   ssh gpu-instance"
echo "   ls -lh /fsx/models/${MODEL_POOL}/"
echo "   cat /fsx/models/${MODEL_POOL}/config.json"
echo ""
echo "2. Update global model registry on FSx:"
echo "   # Copy registry entry to FSx"
echo "   scp ${REGISTRY_FILE} gpu-instance:/tmp/"
echo "   ssh gpu-instance"
echo "   # Merge into /fsx/metadata/model-registry.json"
echo ""
echo "3. Test model loading:"
echo "   curl http://localhost:8080/metrics"
echo "   # Should show ${MODEL_POOL} in available_models"
echo ""
echo "4. Test inference:"
echo "   # Send inference request with X-Model-Pool: ${MODEL_POOL}"
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Upload Complete!${NC}"
echo -e "${GREEN}========================================${NC}"

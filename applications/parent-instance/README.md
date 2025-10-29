# Parent Instance Application

## Overview

The **Parent Instance Application** runs on GPU EC2 instances (g6e.2xlarge) outside the Nitro Enclave. It handles:

- Receiving encrypted requests from the Regional Router
- Communicating with Nitro Enclave via vsock for decryption/encryption
- Running GPU inference on plaintext (never sees encrypted data or KMS keys)
- Loading models from FSx Lustre
- Returning encrypted responses

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ GPU Instance (g6e.2xlarge)                                  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Parent Instance Application (Port 8080)              │  │
│  │                                                       │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │ parent_app.py                                  │  │  │
│  │  │ - Flask HTTP server                            │  │  │
│  │  │ - /inference endpoint                          │  │  │
│  │  │ - /health endpoint                             │  │  │
│  │  │ - /metrics endpoint                            │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  │                                                       │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │ vsock_handler.py                               │  │  │
│  │  │ - Connect to enclave (CID 16, port 5000)       │  │  │
│  │  │ - Send decrypt/encrypt requests                │  │  │
│  │  │ - Handle vsock protocol                        │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  │                                                       │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │ gpu_inference.py                               │  │  │
│  │  │ - Initialize CUDA/GPU                          │  │  │
│  │  │ - Run inference with vLLM                      │  │  │
│  │  │ - Monitor GPU health                           │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  │                                                       │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │ model_loader.py                                │  │  │
│  │  │ - Load models from FSx Lustre                  │  │  │
│  │  │ - Manage model cache                           │  │  │
│  │  │ - On-demand model loading                      │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Nitro Enclave (4GB RAM, 2 vCPUs)                     │  │
│  │ - Decrypt/encrypt via vsock                          │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ GPU (NVIDIA L40S, 48GB VRAM)                         │  │
│  │ - Run inference on plaintext                         │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ FSx Lustre (/fsx)                                    │  │
│  │ - Model storage                                      │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Request Flow

```
1. Regional Router sends encrypted request
   ↓ HTTP POST /inference
2. Parent receives encrypted payload
   ↓
3. Parent sends to enclave via vsock: "decrypt"
   ↓
4. Enclave decrypts with KMS + attestation
   ↓
5. Enclave returns plaintext to parent via vsock
   ↓
6. Parent runs GPU inference on plaintext
   ↓ CUDA/vLLM
7. GPU returns inference result
   ↓
8. Parent sends result to enclave via vsock: "encrypt"
   ↓
9. Enclave encrypts with KMS
   ↓
10. Enclave returns encrypted response via vsock
    ↓
11. Parent returns encrypted response to Regional Router
```

## Files

| File | Purpose |
|------|---------|
| `parent_app.py` | Main Flask application with HTTP endpoints |
| `vsock_handler.py` | vsock communication with enclave |
| `gpu_inference.py` | GPU inference with vLLM |
| `model_loader.py` | Model loading from FSx Lustre |
| `requirements.txt` | Python dependencies |

## Installation

### Prerequisites

1. **EC2 Instance**: g6e.2xlarge with Nitro Enclaves enabled
2. **NVIDIA Driver**: Version 535+ for L40S GPU
3. **CUDA**: Version 12.1+
4. **Python**: Version 3.11+
5. **FSx Lustre**: Mounted at `/fsx`
6. **Nitro Enclave**: Running and connected

### Install Dependencies

```bash
# Update system
sudo yum update -y

# Install Python 3.11
sudo yum install python3.11 python3.11-pip -y

# Install NVIDIA driver (if not already installed)
sudo yum install -y kernel-devel-$(uname -r) kernel-headers-$(uname -r)
aws s3 cp --recursive s3://ec2-linux-nvidia-drivers/latest/ .
chmod +x NVIDIA-Linux-x86_64*.run
sudo /bin/sh ./NVIDIA-Linux-x86_64*.run --silent

# Verify GPU
nvidia-smi

# Install Python dependencies
cd /opt/mrgc/applications/parent-instance
python3.11 -m pip install -r requirements.txt

# Install PyTorch with CUDA
python3.11 -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install vLLM for fast inference
python3.11 -m pip install vllm

# Install additional ML libraries
python3.11 -m pip install transformers accelerate bitsandbytes
```

### Mount FSx Lustre

```bash
# Install Lustre client
sudo amazon-linux-extras install -y lustre

# Create mount point
sudo mkdir -p /fsx

# Mount FSx
sudo mount -t lustre fs-xxxxx.fsx.us-east-1.amazonaws.com@tcp:/fsx /fsx

# Add to /etc/fstab for auto-mount
echo "fs-xxxxx.fsx.us-east-1.amazonaws.com@tcp:/fsx /fsx lustre defaults,_netdev 0 0" | sudo tee -a /etc/fstab

# Verify mount
df -h | grep fsx
```

### Start Nitro Enclave

```bash
# Run enclave (see Nitro Enclave README)
nitro-cli run-enclave \
  --eif-path /opt/mrgc/mrgc-enclave.eif \
  --memory 4096 \
  --cpu-count 2

# Verify enclave is running
nitro-cli describe-enclaves
```

## Running the Application

### Development Mode

```bash
# Run directly
cd /opt/mrgc/applications/parent-instance
python3.11 parent_app.py
```

### Production Mode with systemd

Create a systemd service:

```bash
# Create service file
sudo tee /etc/systemd/system/mrgc-parent.service > /dev/null <<EOF
[Unit]
Description=MRGC Parent Instance Application
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/opt/mrgc/applications/parent-instance
ExecStart=/usr/bin/python3.11 parent_app.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
sudo systemctl daemon-reload

# Enable and start service
sudo systemctl enable mrgc-parent
sudo systemctl start mrgc-parent

# Check status
sudo systemctl status mrgc-parent

# View logs
sudo journalctl -u mrgc-parent -f
```

## API Endpoints

### POST /inference

Receive encrypted inference request.

**Request:**
```
POST /inference HTTP/1.1
Host: 10.66.1.10:8080
Content-Type: application/octet-stream
X-KMS-Key-ARN: arn:aws:kms:us-east-1:123456789012:key/abc-123
X-Tenant-ID: tenant-123
X-Model-Pool: model-a
X-Request-ID: req-abc-123

<encrypted payload bytes>
```

**Response:**
```
HTTP/1.1 200 OK
Content-Type: application/octet-stream

<encrypted result bytes>
```

### GET /health

Check instance health.

**Response:**
```json
{
  "status": "healthy",
  "ready": true,
  "enclave_healthy": true,
  "gpu_healthy": true,
  "models_loaded": ["model-a", "model-b"]
}
```

### GET /metrics

Get instance metrics.

**Response:**
```json
{
  "gpu_stats": {
    "gpu_available": true,
    "gpu_memory_total_mb": 49152,
    "gpu_memory_used_mb": 15000,
    "gpu_memory_usage_pct": 30.5,
    "total_requests": 1234,
    "failed_requests": 5,
    "success_rate": 99.6,
    "avg_inference_time_seconds": 0.45
  },
  "model_stats": {
    "fsx_available": true,
    "loaded_models": 2,
    "available_models": 5,
    "total_loads": 3,
    "failed_loads": 0,
    "avg_load_time_seconds": 35.2,
    "models": ["model-a", "model-b"]
  },
  "enclave_connected": true
}
```

## Configuration

### Environment Variables

```bash
# FSx mount point
export FSX_MOUNT_POINT=/fsx

# Enclave vsock configuration
export ENCLAVE_CID=16
export ENCLAVE_PORT=5000

# HTTP server
export HTTP_PORT=8080
export HTTP_HOST=0.0.0.0

# Model configuration
export DEFAULT_MODEL_POOL=model-a
export GPU_MEMORY_UTILIZATION=0.90

# Logging
export LOG_LEVEL=INFO
```

## Monitoring

### GPU Metrics

Monitor GPU utilization:
```bash
# Real-time GPU stats
nvidia-smi -l 1

# GPU utilization
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv -l 1
```

### Application Logs

```bash
# View logs in real-time
sudo journalctl -u mrgc-parent -f

# Search for errors
sudo journalctl -u mrgc-parent | grep ERROR

# View logs for specific request
sudo journalctl -u mrgc-parent | grep "req-abc-123"
```

### Health Checks

```bash
# Check health endpoint
curl http://localhost:8080/health

# Check metrics
curl http://localhost:8080/metrics

# Test inference (with mock encrypted data)
curl -X POST http://localhost:8080/inference \
  -H "X-KMS-Key-ARN: arn:aws:kms:us-east-1:123456789012:key/test" \
  -H "X-Tenant-ID: tenant-test" \
  -H "X-Model-Pool: model-a" \
  -H "X-Request-ID: test-123" \
  --data-binary "@encrypted_request.bin"
```

## Troubleshooting

### Issue: Cannot connect to enclave

**Check:**
1. Enclave is running: `nitro-cli describe-enclaves`
2. Enclave CID is 16: Check output of describe-enclaves
3. vsock port is 5000: Check enclave logs

```bash
# Check enclave status
nitro-cli describe-enclaves

# View enclave logs
nitro-cli console --enclave-id <enclave-id>
```

### Issue: GPU not detected

**Check:**
1. NVIDIA driver installed: `nvidia-smi`
2. CUDA available: `python3 -c "import torch; print(torch.cuda.is_available())"`
3. GPU permissions: `ls -l /dev/nvidia*`

```bash
# Check NVIDIA driver
nvidia-smi

# Reinstall driver if needed
sudo yum install -y kernel-devel kernel-headers
sudo sh ./NVIDIA-Linux-x86_64*.run --silent
```

### Issue: FSx not mounted

**Check:**
1. Mount point exists: `ls -l /fsx`
2. FSx file system is available
3. Network connectivity to FSx

```bash
# Check mount
df -h | grep fsx

# Remount FSx
sudo mount -t lustre fs-xxxxx.fsx.us-east-1.amazonaws.com@tcp:/fsx /fsx

# Check mount in /etc/fstab
cat /etc/fstab | grep fsx
```

### Issue: Model loading fails

**Check:**
1. FSx is mounted
2. Model files exist: `ls -l /fsx/models/model-a/`
3. Permissions: `ls -l /fsx/models/`
4. Disk space: `df -h /fsx`

```bash
# List available models
ls -l /fsx/models/

# Check model files
ls -l /fsx/models/model-a/

# Test FSx read
cat /fsx/models/model-a/config.json
```

### Issue: Out of GPU memory

**Symptoms**: CUDA out of memory errors

**Solutions**:
1. Reduce `gpu_memory_utilization` to 0.80 or lower
2. Unload unused models
3. Use smaller batch sizes
4. Enable model quantization (8-bit or 4-bit)

```bash
# Check GPU memory
nvidia-smi

# View loaded models via API
curl http://localhost:8080/metrics | jq '.model_stats.models'
```

## Performance

| Operation | Latency |
|-----------|---------|
| vsock roundtrip | 1-2ms |
| KMS decrypt (in enclave) | 50-100ms |
| Model load (FSx, first time) | 30-45s |
| Model load (FSx, cached) | 5-10s |
| GPU inference (7B model) | 100-500ms |
| KMS encrypt (in enclave) | 50-100ms |
| **Total request latency** | **200-700ms** |

### Optimization Tips

1. **Preload models** on startup to avoid first-request latency
2. **Use vLLM** instead of vanilla PyTorch (2-3x faster)
3. **Enable Flash Attention 2** for faster inference
4. **Use 8-bit quantization** to fit larger models in GPU memory
5. **Tune `gpu_memory_utilization`** based on model size

## Security

### What Parent Can See

✅ **Parent CAN see**:
- Encrypted requests (ciphertext)
- Encrypted responses (ciphertext)
- Model files (non-sensitive)
- GPU metrics

❌ **Parent CANNOT see**:
- Plaintext requests
- Plaintext responses
- KMS keys
- Tenant secrets

### Security Boundaries

```
┌─────────────────────────────────────┐
│ Nitro Enclave (Hardware Isolated)   │
│ - Plaintext data                    │
│ - KMS keys                          │
│ - Attestation documents             │
│ - Memory encrypted                  │
└─────────────────────────────────────┘
              ↕ vsock (encrypted channel)
┌─────────────────────────────────────┐
│ Parent Instance                     │
│ - Encrypted data only               │
│ - GPU compute                       │
│ - No access to enclave memory       │
└─────────────────────────────────────┘
```

## Next Steps

1. Complete Feature 4: FSx Lustre setup across 3 regions
2. Complete Feature 5: Regional Router with intelligent load balancing
3. Complete Feature 6: Auto-scaling based on RPS
4. Complete Feature 7: Car Wash secure cleanup
5. Deploy to production
6. Load test and optimize

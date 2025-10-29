#!/usr/bin/env python3
"""
Model Loader for Parent Instance

Loads LLM models from FSx Lustre and manages model cache.

FSx Lustre provides:
- High-throughput model loading (30-45 seconds for 7B model)
- Shared storage across all GPU instances in region
- Automatic S3 data repository integration
- File-level caching

Model Organization:
/fsx/
  ├── models/
  │   ├── model-a/          # Model pool A
  │   │   ├── config.json
  │   │   ├── pytorch_model.bin
  │   │   └── tokenizer.json
  │   ├── model-b/          # Model pool B
  │   └── model-c/          # Model pool C
  └── metadata/
      └── model-registry.json
"""

import logging
import os
import json
import time
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class ModelLoader:
    """Manages model loading from FSx Lustre"""

    # FSx mount point
    FSX_MOUNT_POINT = "/fsx"
    MODELS_DIR = "/fsx/models"
    METADATA_DIR = "/fsx/metadata"

    def __init__(self):
        """Initialize model loader"""
        logger.info("Initializing model loader")

        # Model cache (model_pool -> model_info)
        self.loaded_models: Dict[str, Dict[str, Any]] = {}

        # Model loading stats
        self.total_loads = 0
        self.total_load_time = 0.0
        self.failed_loads = 0

        # Check FSx availability
        self.fsx_available = self._check_fsx_available()

    def _check_fsx_available(self) -> bool:
        """
        Check if FSx Lustre is mounted and available

        Returns:
            True if FSx is available
        """
        try:
            # Check if mount point exists
            if not os.path.exists(self.FSX_MOUNT_POINT):
                logger.error(f"FSx mount point not found: {self.FSX_MOUNT_POINT}")
                return False

            # Check if models directory exists
            if not os.path.exists(self.MODELS_DIR):
                logger.warning(f"Models directory not found: {self.MODELS_DIR}")
                # Create it
                os.makedirs(self.MODELS_DIR, exist_ok=True)

            # Check if metadata directory exists
            if not os.path.exists(self.METADATA_DIR):
                logger.warning(f"Metadata directory not found: {self.METADATA_DIR}")
                os.makedirs(self.METADATA_DIR, exist_ok=True)

            # Test read/write
            test_file = os.path.join(self.FSX_MOUNT_POINT, '.fsx_test')
            with open(test_file, 'w') as f:
                f.write('test')

            with open(test_file, 'r') as f:
                content = f.read()

            os.remove(test_file)

            if content != 'test':
                logger.error("FSx read/write test failed")
                return False

            logger.info("✓ FSx Lustre is available")
            return True

        except Exception as e:
            logger.error(f"Error checking FSx availability: {e}")
            return False

    def load_default_models(self) -> bool:
        """
        Load default models on startup

        Returns:
            True if loaded successfully
        """
        logger.info("Loading default models")

        if not self.fsx_available:
            logger.error("FSx not available, cannot load models")
            return False

        try:
            # Read model registry
            registry_path = os.path.join(self.METADATA_DIR, 'model-registry.json')

            if not os.path.exists(registry_path):
                logger.warning("Model registry not found, no default models to load")
                return True

            with open(registry_path, 'r') as f:
                registry = json.load(f)

            # Load models marked as preload
            for model_pool, model_info in registry.items():
                if model_info.get('preload', False):
                    logger.info(f"Preloading model: {model_pool}")
                    self.load_model(model_pool)

            return True

        except Exception as e:
            logger.error(f"Error loading default models: {e}", exc_info=True)
            return False

    def load_model(self, model_pool: str) -> bool:
        """
        Load model from FSx Lustre

        Args:
            model_pool: Model pool name (e.g., 'model-a')

        Returns:
            True if loaded successfully
        """
        logger.info(f"Loading model: {model_pool}")

        if model_pool in self.loaded_models:
            logger.info(f"Model already loaded: {model_pool}")
            return True

        if not self.fsx_available:
            logger.error("FSx not available")
            return False

        try:
            load_start = time.time()

            # Get model path
            model_path = os.path.join(self.MODELS_DIR, model_pool)

            if not os.path.exists(model_path):
                logger.error(f"Model path not found: {model_path}")
                self.failed_loads += 1
                return False

            # Check required files
            required_files = ['config.json']
            for file in required_files:
                file_path = os.path.join(model_path, file)
                if not os.path.exists(file_path):
                    logger.error(f"Required file not found: {file_path}")
                    self.failed_loads += 1
                    return False

            # Read model config
            config_path = os.path.join(model_path, 'config.json')
            with open(config_path, 'r') as f:
                config = json.load(f)

            # In production, load model with PyTorch/vLLM:
            #
            # from transformers import AutoModelForCausalLM, AutoTokenizer
            # import torch
            #
            # # Load tokenizer
            # tokenizer = AutoTokenizer.from_pretrained(model_path)
            #
            # # Load model to GPU
            # model = AutoModelForCausalLM.from_pretrained(
            #     model_path,
            #     torch_dtype=torch.float16,
            #     device_map="auto"
            # )

            # For development, store metadata
            load_time = time.time() - load_start

            model_info = {
                'model_pool': model_pool,
                'model_path': model_path,
                'config': config,
                'loaded_at': time.time(),
                'load_time_seconds': load_time,
                'model_size_mb': self._get_directory_size(model_path)
            }

            self.loaded_models[model_pool] = model_info

            # Track stats
            self.total_loads += 1
            self.total_load_time += load_time

            logger.info(f"✓ Model loaded: {model_pool} ({load_time:.2f}s, {model_info['model_size_mb']:.0f} MB)")

            return True

        except Exception as e:
            logger.error(f"Error loading model {model_pool}: {e}", exc_info=True)
            self.failed_loads += 1
            return False

    def get_model(self, model_pool: str) -> Optional[Dict[str, Any]]:
        """
        Get loaded model

        If model is not loaded, attempt to load it on-demand.

        Args:
            model_pool: Model pool name

        Returns:
            Model info dict or None if not available
        """
        # Check if already loaded
        if model_pool in self.loaded_models:
            return self.loaded_models[model_pool]

        # Try to load on-demand
        logger.info(f"Model not loaded, loading on-demand: {model_pool}")

        if self.load_model(model_pool):
            return self.loaded_models[model_pool]

        return None

    def unload_model(self, model_pool: str) -> bool:
        """
        Unload model from memory

        Args:
            model_pool: Model pool to unload

        Returns:
            True if unloaded successfully
        """
        logger.info(f"Unloading model: {model_pool}")

        if model_pool not in self.loaded_models:
            logger.warning(f"Model not loaded: {model_pool}")
            return False

        try:
            # In production, free GPU memory:
            # del self.loaded_models[model_pool]['model']
            # del self.loaded_models[model_pool]['tokenizer']
            # import torch
            # torch.cuda.empty_cache()

            del self.loaded_models[model_pool]

            logger.info(f"✓ Model unloaded: {model_pool}")
            return True

        except Exception as e:
            logger.error(f"Error unloading model: {e}")
            return False

    def get_loaded_models(self) -> List[str]:
        """
        Get list of loaded models

        Returns:
            List of model pool names
        """
        return list(self.loaded_models.keys())

    def get_available_models(self) -> List[str]:
        """
        Get list of available models in FSx

        Returns:
            List of model pool names
        """
        if not self.fsx_available:
            return []

        try:
            models = []

            if os.path.exists(self.MODELS_DIR):
                for entry in os.listdir(self.MODELS_DIR):
                    model_path = os.path.join(self.MODELS_DIR, entry)
                    if os.path.isdir(model_path):
                        # Check if it has config.json
                        config_path = os.path.join(model_path, 'config.json')
                        if os.path.exists(config_path):
                            models.append(entry)

            return models

        except Exception as e:
            logger.error(f"Error listing available models: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """
        Get model loading stats

        Returns:
            Dict with stats
        """
        avg_load_time = 0.0
        if self.total_loads > 0:
            avg_load_time = self.total_load_time / self.total_loads

        return {
            'fsx_available': self.fsx_available,
            'loaded_models': len(self.loaded_models),
            'available_models': len(self.get_available_models()),
            'total_loads': self.total_loads,
            'failed_loads': self.failed_loads,
            'avg_load_time_seconds': avg_load_time,
            'models': list(self.loaded_models.keys())
        }

    def _get_directory_size(self, path: str) -> float:
        """
        Get directory size in MB

        Args:
            path: Directory path

        Returns:
            Size in MB
        """
        try:
            total_size = 0

            for dirpath, dirnames, filenames in os.walk(path):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    if os.path.exists(file_path):
                        total_size += os.path.getsize(file_path)

            return total_size / (1024 * 1024)  # Convert to MB

        except Exception as e:
            logger.error(f"Error getting directory size: {e}")
            return 0.0


# FSx Lustre Setup Notes:
#
# 1. Mount FSx Lustre on EC2 instance:
#    sudo mkdir /fsx
#    sudo mount -t lustre fs-xxxxx.fsx.us-east-1.amazonaws.com@tcp:/fsx /fsx
#
# 2. Add to /etc/fstab for automatic mounting:
#    fs-xxxxx.fsx.us-east-1.amazonaws.com@tcp:/fsx /fsx lustre defaults,_netdev 0 0
#
# 3. Verify mount:
#    df -h | grep fsx
#    # Should show: fs-xxxxx.fsx.us-east-1.amazonaws.com@tcp:/fsx  1.2T  100G  1.1T   9% /fsx
#
# 4. Upload models to FSx:
#    aws s3 sync s3://my-models-bucket/llama-2-7b /fsx/models/model-a/
#
# 5. Create model registry:
#    cat > /fsx/metadata/model-registry.json <<EOF
#    {
#      "model-a": {
#        "name": "Llama 2 7B",
#        "path": "/fsx/models/model-a",
#        "preload": true,
#        "size_gb": 13.5
#      },
#      "model-b": {
#        "name": "Mistral 7B",
#        "path": "/fsx/models/model-b",
#        "preload": false,
#        "size_gb": 14.2
#      }
#    }
#    EOF
#
# 6. Performance:
#    - Initial load: 30-45 seconds (from S3)
#    - Cached load: 5-10 seconds (from FSx)
#    - Throughput: 1-2 GB/s per instance

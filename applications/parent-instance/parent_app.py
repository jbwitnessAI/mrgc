#!/usr/bin/env python3
"""
Parent Instance Application for Multi-Region GPU Cluster

Runs on the parent EC2 instance (outside Nitro Enclave) and handles:
1. Receive encrypted requests from Regional Router
2. Forward to enclave for decryption
3. Run GPU inference on plaintext
4. Send result to enclave for encryption
5. Return encrypted response

Key Security Property:
- Parent instance NEVER sees plaintext data or KMS keys
- All encryption/decryption happens in enclave
- Parent only handles encrypted data and GPU compute
"""

import logging
import sys
import json
import base64
from typing import Dict, Optional, Tuple
from flask import Flask, request, jsonify
import time

from vsock_handler import VsockHandler
from gpu_inference import GPUInferenceEngine
from model_loader import ModelLoader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[PARENT] %(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Flask app for receiving requests
app = Flask(__name__)


class ParentApp:
    """Main parent instance application"""

    def __init__(self):
        """Initialize parent application"""
        logger.info("Initializing parent instance application")

        # Initialize vsock handler for enclave communication
        self.vsock_handler = VsockHandler()

        # Initialize model loader
        self.model_loader = ModelLoader()

        # Initialize GPU inference engine
        self.gpu_engine = GPUInferenceEngine(model_loader=self.model_loader)

        # Application state
        self.ready = False

    def start(self):
        """
        Start parent application

        This:
        1. Connects to enclave via vsock
        2. Loads models from FSx Lustre
        3. Initializes GPU
        4. Starts HTTP server
        """
        logger.info("Starting parent instance application")

        # Step 1: Connect to enclave
        logger.info("Connecting to Nitro Enclave...")
        if not self.vsock_handler.connect():
            logger.error("Failed to connect to enclave")
            sys.exit(1)

        # Check enclave health
        if not self.vsock_handler.health_check():
            logger.error("Enclave health check failed")
            sys.exit(1)

        logger.info("✓ Connected to enclave")

        # Step 2: Initialize GPU
        logger.info("Initializing GPU...")
        if not self.gpu_engine.initialize():
            logger.error("Failed to initialize GPU")
            sys.exit(1)

        logger.info("✓ GPU initialized")

        # Step 3: Load initial models
        logger.info("Loading models from FSx Lustre...")
        if not self.model_loader.load_default_models():
            logger.warning("Failed to load default models (will load on-demand)")

        logger.info("✓ Models loaded")

        # Ready to receive requests
        self.ready = True
        logger.info("Parent instance ready to process requests")

    def process_request(
        self,
        encrypted_payload: bytes,
        kms_key_arn: str,
        tenant_id: str,
        model_pool: str,
        request_id: str
    ) -> Tuple[bytes, int]:
        """
        Process inference request

        Flow:
        1. Send encrypted request to enclave for decryption
        2. Receive plaintext from enclave
        3. Run GPU inference on plaintext
        4. Send result to enclave for encryption
        5. Return encrypted result

        Args:
            encrypted_payload: Encrypted request from tenant
            kms_key_arn: Tenant's KMS key ARN
            tenant_id: Tenant ID
            model_pool: Model pool to use
            request_id: Unique request ID

        Returns:
            Tuple of (encrypted_response, status_code)
        """
        logger.info(f"Processing request {request_id} for tenant {tenant_id}")

        try:
            # Step 1: Send to enclave for decryption
            logger.info(f"[{request_id}] Sending to enclave for decryption")

            plaintext_response = self.vsock_handler.decrypt(
                encrypted_payload=encrypted_payload,
                kms_key_arn=kms_key_arn,
                tenant_id=tenant_id,
                request_id=request_id
            )

            if not plaintext_response:
                logger.error(f"[{request_id}] Decryption failed")
                return self._create_error_response("Decryption failed"), 400

            logger.info(f"[{request_id}] ✓ Decrypted ({len(plaintext_response)} bytes)")

            # Step 2: Parse request
            try:
                request_data = json.loads(plaintext_response.decode('utf-8'))
            except Exception as e:
                logger.error(f"[{request_id}] Invalid request format: {e}")
                return self._create_error_response("Invalid request format"), 400

            # Step 3: Run GPU inference
            logger.info(f"[{request_id}] Running GPU inference")

            inference_start = time.time()

            result = self.gpu_engine.run_inference(
                prompt=request_data.get('prompt'),
                model_pool=model_pool,
                max_tokens=request_data.get('max_tokens', 100),
                temperature=request_data.get('temperature', 0.7),
                request_id=request_id
            )

            inference_time = time.time() - inference_start

            if not result:
                logger.error(f"[{request_id}] Inference failed")
                return self._create_error_response("Inference failed"), 500

            logger.info(f"[{request_id}] ✓ Inference complete ({inference_time:.2f}s)")

            # Step 4: Prepare result
            result_data = {
                'result': result,
                'inference_time_ms': int(inference_time * 1000),
                'model_pool': model_pool,
                'request_id': request_id
            }

            result_json = json.dumps(result_data).encode('utf-8')

            # Step 5: Send to enclave for encryption
            logger.info(f"[{request_id}] Sending to enclave for encryption")

            encrypted_result = self.vsock_handler.encrypt(
                plaintext_result=result_json,
                kms_key_arn=kms_key_arn,
                request_id=request_id
            )

            if not encrypted_result:
                logger.error(f"[{request_id}] Encryption failed")
                return self._create_error_response("Encryption failed"), 500

            logger.info(f"[{request_id}] ✓ Encrypted ({len(encrypted_result)} bytes)")

            # Step 6: Return encrypted result
            logger.info(f"[{request_id}] Request complete")
            return encrypted_result, 200

        except Exception as e:
            logger.error(f"[{request_id}] Error processing request: {e}", exc_info=True)
            return self._create_error_response(str(e)), 500

    def _create_error_response(self, error_message: str) -> bytes:
        """
        Create error response

        Args:
            error_message: Error description

        Returns:
            Error response as bytes
        """
        error_response = {
            'error': error_message,
            'success': False
        }

        return json.dumps(error_response).encode('utf-8')


# Global parent app instance
parent_app = ParentApp()


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    if not parent_app.ready:
        return jsonify({
            'status': 'initializing',
            'ready': False
        }), 503

    # Check enclave health
    enclave_healthy = parent_app.vsock_handler.health_check()

    # Check GPU health
    gpu_healthy = parent_app.gpu_engine.is_healthy()

    healthy = enclave_healthy and gpu_healthy

    return jsonify({
        'status': 'healthy' if healthy else 'unhealthy',
        'ready': True,
        'enclave_healthy': enclave_healthy,
        'gpu_healthy': gpu_healthy,
        'models_loaded': parent_app.model_loader.get_loaded_models()
    }), 200 if healthy else 503


@app.route('/inference', methods=['POST'])
def inference():
    """
    Inference endpoint

    Receives encrypted requests from Regional Router
    """
    if not parent_app.ready:
        return jsonify({
            'error': 'Instance not ready',
            'success': False
        }), 503

    try:
        # Extract request parameters
        encrypted_payload = request.data
        kms_key_arn = request.headers.get('X-KMS-Key-ARN')
        tenant_id = request.headers.get('X-Tenant-ID')
        model_pool = request.headers.get('X-Model-Pool', 'default')
        request_id = request.headers.get('X-Request-ID', 'unknown')

        # Validate required parameters
        if not encrypted_payload:
            return jsonify({'error': 'No payload provided', 'success': False}), 400

        if not kms_key_arn:
            return jsonify({'error': 'No KMS key ARN provided', 'success': False}), 400

        if not tenant_id:
            return jsonify({'error': 'No tenant ID provided', 'success': False}), 400

        # Process request
        encrypted_result, status_code = parent_app.process_request(
            encrypted_payload=encrypted_payload,
            kms_key_arn=kms_key_arn,
            tenant_id=tenant_id,
            model_pool=model_pool,
            request_id=request_id
        )

        # Return encrypted result
        return encrypted_result, status_code

    except Exception as e:
        logger.error(f"Error in inference endpoint: {e}", exc_info=True)
        return jsonify({
            'error': str(e),
            'success': False
        }), 500


@app.route('/metrics', methods=['GET'])
def metrics():
    """
    Metrics endpoint for monitoring

    Returns:
    - GPU utilization
    - Memory usage
    - Request counts
    - Model cache stats
    """
    return jsonify({
        'gpu_stats': parent_app.gpu_engine.get_stats(),
        'model_stats': parent_app.model_loader.get_stats(),
        'enclave_connected': parent_app.vsock_handler.is_connected()
    }), 200


def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("AWS Parent Instance - Multi-Region GPU Cluster")
    logger.info("Version: 1.0.0")
    logger.info("=" * 60)

    # Start parent application
    parent_app.start()

    # Run Flask server
    logger.info("Starting HTTP server on port 8080...")
    app.run(
        host='0.0.0.0',
        port=8080,
        threaded=True  # Handle multiple requests concurrently
    )


if __name__ == '__main__':
    main()

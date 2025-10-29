#!/usr/bin/env python3
"""
Regional Router Application

Runs on ECS Fargate and routes inference requests to GPU instances.

Key Responsibilities:
1. Receive requests from NLB/Global Accelerator
2. Select best GPU instance based on routing score
3. Forward encrypted request to selected instance
4. Return encrypted response to client

Routing Score Algorithm (0-100, higher is better):
- Queue depth: 50% weight (fewer queued requests = higher score)
- Latency: 30% weight (lower latency = higher score)
- Health: 20% weight (healthier = higher score)
"""

import logging
import sys
import time
import requests
from typing import Optional, Tuple
from flask import Flask, request, Response, jsonify

# Import from global-state application
sys.path.append('/opt/mrgc/applications/global-state')
from instance_registry import InstanceRegistry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[ROUTER] %(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)


class RegionalRouter:
    """Regional router for GPU cluster"""

    def __init__(self, region: str):
        """
        Initialize regional router

        Args:
            region: AWS region (e.g., us-east-1)
        """
        logger.info(f"Initializing regional router for {region}")

        self.region = region

        # Initialize instance registry
        self.registry = InstanceRegistry(region=region)

        # Router stats
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_routing_time = 0.0

        # Health check interval
        self.last_health_check = time.time()
        self.health_check_interval = 30  # seconds

    def select_instance(self, model_pool: str) -> Optional[dict]:
        """
        Select best GPU instance for request

        Uses routing score algorithm to select the best instance:
        - Queue depth (50%): Fewer queued requests
        - Latency (30%): Lower average latency
        - Health (20%): Better health score

        Args:
            model_pool: Model pool requested

        Returns:
            Instance dict or None if no instances available
        """
        # Get all healthy instances in this region with the model
        instances = self.registry.get_instances_by_region_and_model(
            region=self.region,
            model_pool=model_pool
        )

        if not instances:
            logger.warning(f"No instances available for model: {model_pool}")
            return None

        # Filter for healthy instances
        healthy_instances = [
            inst for inst in instances
            if inst.get('status') == 'ready' and inst.get('health_score', 0) > 50
        ]

        if not healthy_instances:
            logger.warning(f"No healthy instances available for model: {model_pool}")
            return None

        # Select instance with highest routing score
        best_instance = max(healthy_instances, key=lambda x: x.get('routing_score', 0))

        logger.info(f"Selected instance: {best_instance['instance_id']} (score: {best_instance.get('routing_score', 0):.1f})")

        return best_instance

    def forward_request(
        self,
        instance: dict,
        encrypted_payload: bytes,
        headers: dict,
        request_id: str
    ) -> Tuple[Optional[bytes], int]:
        """
        Forward request to GPU instance

        Args:
            instance: Instance dict
            encrypted_payload: Encrypted request payload
            headers: Request headers
            request_id: Request ID

        Returns:
            Tuple of (response_data, status_code)
        """
        instance_id = instance['instance_id']
        private_ip = instance['private_ip']

        logger.info(f"[{request_id}] Forwarding to {instance_id} ({private_ip})")

        try:
            # Build URL
            url = f"http://{private_ip}:8080/inference"

            # Forward request
            forward_start = time.time()

            response = requests.post(
                url,
                data=encrypted_payload,
                headers={
                    'Content-Type': 'application/octet-stream',
                    'X-KMS-Key-ARN': headers.get('X-KMS-Key-ARN'),
                    'X-Tenant-ID': headers.get('X-Tenant-ID'),
                    'X-Model-Pool': headers.get('X-Model-Pool'),
                    'X-Request-ID': request_id
                },
                timeout=60  # 60 second timeout
            )

            forward_time = time.time() - forward_start

            logger.info(f"[{request_id}] Response from {instance_id}: {response.status_code} ({forward_time:.2f}s)")

            return response.content, response.status_code

        except requests.exceptions.Timeout:
            logger.error(f"[{request_id}] Timeout forwarding to {instance_id}")
            return None, 504  # Gateway timeout

        except requests.exceptions.ConnectionError:
            logger.error(f"[{request_id}] Connection error forwarding to {instance_id}")
            # Mark instance as unhealthy
            self.registry.update_health(instance_id, health_score=0)
            return None, 503  # Service unavailable

        except Exception as e:
            logger.error(f"[{request_id}] Error forwarding to {instance_id}: {e}", exc_info=True)
            return None, 500

    def process_request(
        self,
        encrypted_payload: bytes,
        headers: dict,
        request_id: str
    ) -> Tuple[Optional[bytes], int]:
        """
        Process inference request

        Flow:
        1. Extract model pool from headers
        2. Select best GPU instance
        3. Forward request to instance
        4. Return response

        Args:
            encrypted_payload: Encrypted request
            headers: Request headers
            request_id: Request ID

        Returns:
            Tuple of (response_data, status_code)
        """
        logger.info(f"[{request_id}] Processing request")

        routing_start = time.time()

        try:
            # Track stats
            self.total_requests += 1

            # Get model pool
            model_pool = headers.get('X-Model-Pool', 'default')

            # Select instance
            instance = self.select_instance(model_pool)

            if not instance:
                logger.error(f"[{request_id}] No instances available")
                self.failed_requests += 1
                return None, 503

            # Forward request
            response_data, status_code = self.forward_request(
                instance=instance,
                encrypted_payload=encrypted_payload,
                headers=headers,
                request_id=request_id
            )

            # Track routing time
            routing_time = time.time() - routing_start
            self.total_routing_time += routing_time

            # Update stats
            if status_code == 200:
                self.successful_requests += 1
            else:
                self.failed_requests += 1

            logger.info(f"[{request_id}] Request complete: {status_code} ({routing_time:.2f}s)")

            return response_data, status_code

        except Exception as e:
            logger.error(f"[{request_id}] Error processing request: {e}", exc_info=True)
            self.failed_requests += 1
            return None, 500

    def run_health_checks(self):
        """
        Run periodic health checks

        This runs asynchronously to keep instance states fresh
        """
        current_time = time.time()

        if current_time - self.last_health_check < self.health_check_interval:
            return

        logger.debug("Running health checks")

        # Refresh instance list
        # The instance registry automatically fetches from DynamoDB
        instances = self.registry.list_instances(region=self.region)

        logger.debug(f"Found {len(instances)} instances in region")

        self.last_health_check = current_time

    def get_stats(self) -> dict:
        """
        Get router statistics

        Returns:
            Stats dict
        """
        avg_routing_time = 0.0
        if self.total_requests > 0:
            avg_routing_time = self.total_routing_time / self.total_requests

        success_rate = 0.0
        if self.total_requests > 0:
            success_rate = (self.successful_requests / self.total_requests) * 100

        return {
            'region': self.region,
            'total_requests': self.total_requests,
            'successful_requests': self.successful_requests,
            'failed_requests': self.failed_requests,
            'success_rate_pct': success_rate,
            'avg_routing_time_seconds': avg_routing_time
        }


# Global router instance
router = RegionalRouter(region='us-east-1')  # Set from environment variable in production


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    # Run health checks
    router.run_health_checks()

    # Get available capacity
    instances = router.registry.list_instances(region=router.region)
    healthy_instances = [i for i in instances if i.get('status') == 'ready']

    return jsonify({
        'status': 'healthy',
        'region': router.region,
        'available_capacity': len(healthy_instances),
        'total_instances': len(instances)
    }), 200


@app.route('/inference', methods=['POST'])
def inference():
    """
    Inference endpoint

    Receives encrypted requests and routes to GPU instances
    """
    try:
        # Run periodic health checks
        router.run_health_checks()

        # Extract request data
        encrypted_payload = request.data
        request_id = request.headers.get('X-Request-ID', f'req-{int(time.time())}')

        # Validate payload
        if not encrypted_payload:
            return jsonify({'error': 'No payload provided', 'success': False}), 400

        # Validate required headers
        required_headers = ['X-KMS-Key-ARN', 'X-Tenant-ID']
        for header in required_headers:
            if not request.headers.get(header):
                return jsonify({'error': f'Missing header: {header}', 'success': False}), 400

        # Process request
        response_data, status_code = router.process_request(
            encrypted_payload=encrypted_payload,
            headers=dict(request.headers),
            request_id=request_id
        )

        if response_data:
            return Response(response_data, status=status_code, mimetype='application/octet-stream')
        else:
            return jsonify({
                'error': 'Request failed',
                'success': False,
                'request_id': request_id
            }), status_code

    except Exception as e:
        logger.error(f"Error in inference endpoint: {e}", exc_info=True)
        return jsonify({
            'error': str(e),
            'success': False
        }), 500


@app.route('/metrics', methods=['GET'])
def metrics():
    """Metrics endpoint"""
    return jsonify(router.get_stats()), 200


def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("Regional Router - Multi-Region GPU Cluster")
    logger.info(f"Region: {router.region}")
    logger.info("Version: 1.0.0")
    logger.info("=" * 60)

    # Run Flask server
    app.run(
        host='0.0.0.0',
        port=8080,
        threaded=True
    )


if __name__ == '__main__':
    main()

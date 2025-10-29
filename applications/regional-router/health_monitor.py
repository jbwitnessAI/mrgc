"""
Health Monitor for Multi-Region GPU Cluster

Monitors health of GPU instances and entire regions, detecting failures
and triggering failover when necessary.
"""

import boto3
import time
import logging
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
from enum import Enum
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class InstanceHealth:
    """Health information for a GPU instance"""
    instance_id: str
    region: str
    status: HealthStatus
    last_check: int
    consecutive_failures: int
    response_time_ms: float
    error_message: Optional[str] = None


@dataclass
class RegionHealth:
    """Health information for an entire region"""
    region: str
    status: HealthStatus
    healthy_instances: int
    total_instances: int
    avg_response_time_ms: float
    last_check: int
    degraded_reason: Optional[str] = None


class HealthMonitor:
    """Monitors health of GPU instances and regions"""

    def __init__(
        self,
        region: str,
        state_manager,
        health_check_interval: int = 30,
        failure_threshold: int = 3,
        timeout_seconds: int = 10
    ):
        """
        Initialize health monitor

        Args:
            region: AWS region this monitor runs in
            state_manager: StateManager instance
            health_check_interval: Seconds between health checks
            failure_threshold: Consecutive failures before marking unhealthy
            timeout_seconds: Health check timeout
        """
        self.region = region
        self.state_mgr = state_manager
        self.health_check_interval = health_check_interval
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds

        # Track consecutive failures per instance
        self.failure_counts: Dict[str, int] = {}

        # EC2 client for checking instance status
        self.ec2 = boto3.client('ec2', region_name=region)

    def check_instance_health(
        self,
        instance_id: str,
        ip_address: str
    ) -> InstanceHealth:
        """
        Check health of a single GPU instance

        Args:
            instance_id: EC2 instance ID
            ip_address: Private IP address

        Returns:
            InstanceHealth object
        """
        start_time = time.time()

        try:
            # Check HTTP health endpoint
            response = requests.get(
                f"http://{ip_address}:8080/health",
                timeout=self.timeout_seconds
            )

            response_time_ms = (time.time() - start_time) * 1000

            if response.status_code == 200:
                # Reset failure count on success
                self.failure_counts[instance_id] = 0

                health_data = response.json()
                queue_depth = health_data.get('queue_depth', 0)

                # Determine health based on queue depth and response time
                if queue_depth > 8 or response_time_ms > 5000:
                    status = HealthStatus.DEGRADED
                else:
                    status = HealthStatus.HEALTHY

                return InstanceHealth(
                    instance_id=instance_id,
                    region=self.region,
                    status=status,
                    last_check=int(time.time()),
                    consecutive_failures=0,
                    response_time_ms=response_time_ms
                )
            else:
                # Non-200 status code
                self.failure_counts[instance_id] = self.failure_counts.get(instance_id, 0) + 1
                consecutive_failures = self.failure_counts[instance_id]

                status = HealthStatus.UNHEALTHY if consecutive_failures >= self.failure_threshold else HealthStatus.DEGRADED

                return InstanceHealth(
                    instance_id=instance_id,
                    region=self.region,
                    status=status,
                    last_check=int(time.time()),
                    consecutive_failures=consecutive_failures,
                    response_time_ms=response_time_ms,
                    error_message=f"HTTP {response.status_code}"
                )

        except requests.exceptions.Timeout:
            self.failure_counts[instance_id] = self.failure_counts.get(instance_id, 0) + 1
            consecutive_failures = self.failure_counts[instance_id]

            return InstanceHealth(
                instance_id=instance_id,
                region=self.region,
                status=HealthStatus.UNHEALTHY if consecutive_failures >= self.failure_threshold else HealthStatus.DEGRADED,
                last_check=int(time.time()),
                consecutive_failures=consecutive_failures,
                response_time_ms=(time.time() - start_time) * 1000,
                error_message="Timeout"
            )

        except Exception as e:
            self.failure_counts[instance_id] = self.failure_counts.get(instance_id, 0) + 1
            consecutive_failures = self.failure_counts[instance_id]

            return InstanceHealth(
                instance_id=instance_id,
                region=self.region,
                status=HealthStatus.UNHEALTHY if consecutive_failures >= self.failure_threshold else HealthStatus.DEGRADED,
                last_check=int(time.time()),
                consecutive_failures=consecutive_failures,
                response_time_ms=0.0,
                error_message=str(e)
            )

    def check_all_instances(self) -> List[InstanceHealth]:
        """
        Check health of all instances in the region

        Returns:
            List of InstanceHealth objects
        """
        # Get all available instances from DynamoDB
        instances = self.state_mgr.get_instances_by_region(
            self.region,
            state="available"
        )

        if not instances:
            logger.info(f"No available instances in {self.region}")
            return []

        health_results = []

        # Check instances in parallel for speed
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_instance = {
                executor.submit(
                    self.check_instance_health,
                    inst['instance_id'],
                    inst['ip_address']
                ): inst for inst in instances
            }

            for future in as_completed(future_to_instance):
                try:
                    health = future.result()
                    health_results.append(health)

                    # Update routing state based on health
                    self._update_routing_health(health)

                except Exception as e:
                    inst = future_to_instance[future]
                    logger.error(f"Health check failed for {inst['instance_id']}: {e}")

        return health_results

    def calculate_region_health(
        self,
        instance_healths: List[InstanceHealth]
    ) -> RegionHealth:
        """
        Calculate overall region health based on instance healths

        Args:
            instance_healths: List of instance health checks

        Returns:
            RegionHealth object
        """
        if not instance_healths:
            return RegionHealth(
                region=self.region,
                status=HealthStatus.UNHEALTHY,
                healthy_instances=0,
                total_instances=0,
                avg_response_time_ms=0.0,
                last_check=int(time.time()),
                degraded_reason="No instances available"
            )

        total_instances = len(instance_healths)
        healthy_instances = sum(
            1 for h in instance_healths
            if h.status == HealthStatus.HEALTHY
        )
        degraded_instances = sum(
            1 for h in instance_healths
            if h.status == HealthStatus.DEGRADED
        )
        unhealthy_instances = sum(
            1 for h in instance_healths
            if h.status == HealthStatus.UNHEALTHY
        )

        # Calculate average response time (only for successful checks)
        successful_checks = [
            h for h in instance_healths
            if h.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
        ]
        avg_response_time = (
            sum(h.response_time_ms for h in successful_checks) / len(successful_checks)
            if successful_checks else 0.0
        )

        # Determine region status
        healthy_percentage = (healthy_instances / total_instances) * 100

        if healthy_percentage >= 80:
            status = HealthStatus.HEALTHY
            degraded_reason = None
        elif healthy_percentage >= 50:
            status = HealthStatus.DEGRADED
            degraded_reason = f"{degraded_instances + unhealthy_instances} instances unhealthy"
        else:
            status = HealthStatus.UNHEALTHY
            degraded_reason = f"Only {healthy_percentage:.1f}% instances healthy"

        return RegionHealth(
            region=self.region,
            status=status,
            healthy_instances=healthy_instances,
            total_instances=total_instances,
            avg_response_time_ms=avg_response_time,
            last_check=int(time.time()),
            degraded_reason=degraded_reason
        )

    def check_ec2_instance_status(self, instance_id: str) -> bool:
        """
        Check EC2 instance status via AWS API

        Args:
            instance_id: EC2 instance ID

        Returns:
            True if instance is running and passing status checks
        """
        try:
            response = self.ec2.describe_instance_status(
                InstanceIds=[instance_id],
                IncludeAllInstances=False  # Only running instances
            )

            if not response['InstanceStatuses']:
                return False

            status = response['InstanceStatuses'][0]

            # Check instance status and system status
            instance_status = status['InstanceStatus']['Status']
            system_status = status['SystemStatus']['Status']

            return instance_status == 'ok' and system_status == 'ok'

        except Exception as e:
            logger.error(f"Failed to check EC2 status for {instance_id}: {e}")
            return False

    def detect_stale_instances(self, timeout_seconds: int = 90) -> List[str]:
        """
        Detect instances that haven't sent heartbeat recently

        Args:
            timeout_seconds: Heartbeat timeout

        Returns:
            List of stale instance IDs
        """
        cutoff = int(time.time()) - timeout_seconds
        instances = self.state_mgr.get_instances_by_region(self.region)

        stale = []
        for inst in instances:
            if inst['state'] in ['available', 'draining']:
                if inst['last_heartbeat'] < cutoff:
                    stale.append(inst['instance_id'])
                    logger.warning(
                        f"Instance {inst['instance_id']} is stale "
                        f"(last heartbeat: {inst['last_heartbeat']})"
                    )

        return stale

    def mark_instance_unhealthy(
        self,
        instance_id: str,
        reason: str
    ) -> bool:
        """
        Mark an instance as unhealthy and remove from routing

        Args:
            instance_id: EC2 instance ID
            reason: Reason for unhealthy status

        Returns:
            True if successful
        """
        logger.warning(f"Marking instance {instance_id} as unhealthy: {reason}")

        # Update routing state to score of 0 (will not receive traffic)
        success = self.state_mgr.update_routing_state(
            instance_id=instance_id,
            region=self.region,
            routing_score=0,
            queue_depth=99,  # High queue depth to avoid routing
            avg_latency_ms=99999.0,
            health_status=HealthStatus.UNHEALTHY.value,
            subnet_cidr="0.0.0.0/0"
        )

        if success:
            # Update instance state to draining
            self.state_mgr.update_instance_state(
                instance_id=instance_id,
                state="draining"
            )

        return success

    def _update_routing_health(self, health: InstanceHealth) -> None:
        """
        Update routing state based on health check

        Args:
            health: InstanceHealth object
        """
        # Get current routing state
        try:
            # Calculate routing score based on health
            if health.status == HealthStatus.HEALTHY:
                # Base score on response time
                base_score = max(0, 100 - (health.response_time_ms / 10))
            elif health.status == HealthStatus.DEGRADED:
                base_score = 50.0
            else:  # UNHEALTHY
                base_score = 0.0

            self.state_mgr.update_routing_state(
                instance_id=health.instance_id,
                region=self.region,
                routing_score=base_score,
                queue_depth=0,  # Will be updated by instance heartbeat
                avg_latency_ms=health.response_time_ms,
                health_status=health.status.value,
                subnet_cidr="0.0.0.0/0"  # Will be updated by instance
            )

        except Exception as e:
            logger.error(f"Failed to update routing health for {health.instance_id}: {e}")

    def run_health_check_loop(self) -> None:
        """
        Run continuous health check loop

        This should be run in a background thread/process
        """
        logger.info(f"Starting health check loop for {self.region}")

        while True:
            try:
                # Check all instances
                instance_healths = self.check_all_instances()

                # Calculate region health
                region_health = self.calculate_region_health(instance_healths)

                # Log region status
                logger.info(
                    f"Region {self.region} health: {region_health.status.value} "
                    f"({region_health.healthy_instances}/{region_health.total_instances} healthy, "
                    f"avg response: {region_health.avg_response_time_ms:.0f}ms)"
                )

                # Detect stale instances
                stale_instances = self.detect_stale_instances()
                for instance_id in stale_instances:
                    self.mark_instance_unhealthy(instance_id, "Stale heartbeat")

                # Sleep until next check
                time.sleep(self.health_check_interval)

            except Exception as e:
                logger.error(f"Health check loop error: {e}", exc_info=True)
                time.sleep(5)  # Short sleep before retry

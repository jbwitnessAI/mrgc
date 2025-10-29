"""
Instance Registry for Multi-Region GPU Cluster

Provides high-level operations for managing GPU instance lifecycle
and state in the global cluster.
"""

import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum

from state_manager import StateManager

logger = logging.getLogger(__name__)


class InstanceState(Enum):
    """GPU instance states"""
    LAUNCHING = "launching"
    AVAILABLE = "available"
    DRAINING = "draining"
    TERMINATED = "terminated"
    QUARANTINED = "quarantined"


class HealthStatus(Enum):
    """Instance health status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class GPUInstance:
    """GPU instance representation"""
    instance_id: str
    region: str
    model_pool: str
    state: InstanceState
    queue_depth: int
    ip_address: str
    subnet_id: str
    availability_zone: str
    last_heartbeat: int
    launch_time: int
    metadata: Dict[str, Any]


@dataclass
class RoutingInfo:
    """Routing information for an instance"""
    instance_id: str
    region: str
    routing_score: float
    queue_depth: int
    avg_latency_ms: float
    health_status: HealthStatus
    subnet_cidr: str
    last_updated: int


class InstanceRegistry:
    """High-level interface for GPU instance registry"""

    def __init__(self, region: str, table_prefix: str = "mrgc"):
        """
        Initialize instance registry

        Args:
            region: AWS region
            table_prefix: DynamoDB table prefix
        """
        self.region = region
        self.state_mgr = StateManager(region, table_prefix)

    def register_new_instance(
        self,
        instance_id: str,
        region: str,
        model_pool: str,
        ip_address: str,
        subnet_id: str,
        availability_zone: str,
        subnet_cidr: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Register a newly launched GPU instance

        Args:
            instance_id: EC2 instance ID
            region: AWS region
            model_pool: Model pool name
            ip_address: Private IP
            subnet_id: Subnet ID
            availability_zone: AZ name
            subnet_cidr: Subnet CIDR for routing affinity
            metadata: Additional metadata

        Returns:
            True if successful
        """
        # Register in main instance table
        success = self.state_mgr.register_instance(
            instance_id=instance_id,
            region=region,
            model_pool=model_pool,
            ip_address=ip_address,
            subnet_id=subnet_id,
            availability_zone=availability_zone,
            metadata=metadata
        )

        if not success:
            return False

        # Initialize routing state with low score (warming up)
        success = self.state_mgr.update_routing_state(
            instance_id=instance_id,
            region=region,
            routing_score=10.0,  # Low initial score during warmup
            queue_depth=0,
            avg_latency_ms=0.0,
            health_status=HealthStatus.HEALTHY.value,
            subnet_cidr=subnet_cidr
        )

        if success:
            logger.info(f"Successfully registered instance {instance_id}")
        else:
            logger.error(f"Failed to initialize routing state for {instance_id}")

        return success

    def mark_instance_available(self, instance_id: str) -> bool:
        """
        Mark instance as available for traffic

        Args:
            instance_id: EC2 instance ID

        Returns:
            True if successful
        """
        success = self.state_mgr.update_instance_state(
            instance_id=instance_id,
            state=InstanceState.AVAILABLE.value,
            queue_depth=0
        )

        if success:
            logger.info(f"Instance {instance_id} marked as available")

        return success

    def begin_draining(self, instance_id: str) -> bool:
        """
        Begin draining instance (preparing for termination)

        Args:
            instance_id: EC2 instance ID

        Returns:
            True if successful
        """
        success = self.state_mgr.update_instance_state(
            instance_id=instance_id,
            state=InstanceState.DRAINING.value
        )

        if success:
            logger.info(f"Instance {instance_id} draining")

        return success

    def quarantine_instance(self, instance_id: str, reason: str) -> bool:
        """
        Quarantine instance due to failed validation

        Args:
            instance_id: EC2 instance ID
            reason: Quarantine reason

        Returns:
            True if successful
        """
        success = self.state_mgr.update_instance_state(
            instance_id=instance_id,
            state=InstanceState.QUARANTINED.value
        )

        if success:
            logger.warning(f"Instance {instance_id} quarantined: {reason}")

        return success

    def get_available_instances(
        self,
        region: Optional[str] = None,
        model_pool: Optional[str] = None
    ) -> List[GPUInstance]:
        """
        Get all available instances

        Args:
            region: Optional region filter
            model_pool: Optional model pool filter

        Returns:
            List of available GPU instances
        """
        if model_pool:
            instances = self.state_mgr.get_instances_by_model_pool(model_pool)
        elif region:
            instances = self.state_mgr.get_instances_by_region(
                region,
                state=InstanceState.AVAILABLE.value
            )
        else:
            instances = self.state_mgr.get_instances_by_region(
                self.region,
                state=InstanceState.AVAILABLE.value
            )

        return [self._dict_to_instance(inst) for inst in instances]

    def get_capacity_by_pool(self, model_pool: str) -> Dict[str, int]:
        """
        Get current capacity for a model pool across all regions

        Args:
            model_pool: Model pool name

        Returns:
            Dictionary of region -> instance count
        """
        instances = self.state_mgr.get_instances_by_model_pool(model_pool)

        capacity = {}
        for inst in instances:
            region = inst['region']
            state = inst['state']

            # Only count non-terminated instances
            if state != InstanceState.TERMINATED.value:
                capacity[region] = capacity.get(region, 0) + 1

        return capacity

    def send_heartbeat(self, instance_id: str, queue_depth: int) -> bool:
        """
        Send heartbeat for instance

        Args:
            instance_id: EC2 instance ID
            queue_depth: Current queue depth

        Returns:
            True if successful
        """
        return self.state_mgr.heartbeat(instance_id, queue_depth)

    def update_routing_metrics(
        self,
        instance_id: str,
        queue_depth: int,
        avg_latency_ms: float,
        health_status: HealthStatus
    ) -> bool:
        """
        Update routing metrics for an instance

        Calculates routing score based on:
        - 50% queue depth (lower is better)
        - 30% latency (lower is better)
        - 20% health status

        Args:
            instance_id: EC2 instance ID
            queue_depth: Current queue depth (0-10)
            avg_latency_ms: Average latency in ms
            health_status: Health status

        Returns:
            True if successful
        """
        # Calculate routing score (0-100, higher is better)
        queue_score = max(0, 100 - (queue_depth * 10))  # 50% weight
        latency_score = max(0, 100 - (avg_latency_ms / 10))  # 30% weight

        health_score = {
            HealthStatus.HEALTHY: 100,
            HealthStatus.DEGRADED: 50,
            HealthStatus.UNHEALTHY: 0
        }.get(health_status, 0)  # 20% weight

        routing_score = (
            (queue_score * 0.5) +
            (latency_score * 0.3) +
            (health_score * 0.2)
        )

        # Get instance details for subnet CIDR
        instances = self.state_mgr.get_instances_by_region(self.region)
        instance = next((i for i in instances if i['instance_id'] == instance_id), None)

        if not instance:
            logger.error(f"Instance {instance_id} not found in registry")
            return False

        # Extract subnet CIDR from metadata or use a default pattern
        subnet_cidr = instance.get('metadata', {}).get('subnet_cidr', '0.0.0.0/0')

        return self.state_mgr.update_routing_state(
            instance_id=instance_id,
            region=self.region,
            routing_score=routing_score,
            queue_depth=queue_depth,
            avg_latency_ms=avg_latency_ms,
            health_status=health_status.value,
            subnet_cidr=subnet_cidr
        )

    def get_best_instances_for_routing(
        self,
        region: str,
        limit: int = 10
    ) -> List[RoutingInfo]:
        """
        Get best instances for routing in a region

        Args:
            region: AWS region
            limit: Maximum number of instances

        Returns:
            List of routing info, sorted by score
        """
        routing_states = self.state_mgr.get_best_instances(region, limit)
        return [self._dict_to_routing_info(rs) for rs in routing_states]

    def get_stale_instances(self, timeout_seconds: int = 60) -> List[str]:
        """
        Get instances that haven't sent heartbeat recently

        Args:
            timeout_seconds: Heartbeat timeout in seconds

        Returns:
            List of stale instance IDs
        """
        import time
        cutoff = int(time.time()) - timeout_seconds

        instances = self.state_mgr.get_instances_by_region(self.region)
        stale = []

        for inst in instances:
            if inst['state'] in [InstanceState.AVAILABLE.value, InstanceState.DRAINING.value]:
                if inst['last_heartbeat'] < cutoff:
                    stale.append(inst['instance_id'])

        return stale

    @staticmethod
    def _dict_to_instance(data: Dict[str, Any]) -> GPUInstance:
        """Convert DynamoDB item to GPUInstance"""
        import json
        return GPUInstance(
            instance_id=data['instance_id'],
            region=data['region'],
            model_pool=data['model_pool'],
            state=InstanceState(data['state']),
            queue_depth=data['queue_depth'],
            ip_address=data['ip_address'],
            subnet_id=data['subnet_id'],
            availability_zone=data['availability_zone'],
            last_heartbeat=data['last_heartbeat'],
            launch_time=data['launch_time'],
            metadata=json.loads(data.get('metadata', '{}'))
        )

    @staticmethod
    def _dict_to_routing_info(data: Dict[str, Any]) -> RoutingInfo:
        """Convert DynamoDB item to RoutingInfo"""
        return RoutingInfo(
            instance_id=data['instance_id'],
            region=data['region'],
            routing_score=float(data['routing_score']),
            queue_depth=data['queue_depth'],
            avg_latency_ms=float(data['avg_latency_ms']),
            health_status=HealthStatus(data['health_status']),
            subnet_cidr=data['subnet_cidr'],
            last_updated=data['last_updated']
        )

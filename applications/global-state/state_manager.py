"""
Global State Manager for Multi-Region GPU Cluster

Provides unified interface for managing DynamoDB Global Tables state
across all regions.
"""

import boto3
import time
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class StateManager:
    """Manages global state in DynamoDB Global Tables"""

    def __init__(self, region: str, table_prefix: str = "mrgc"):
        """
        Initialize state manager

        Args:
            region: AWS region (us-east-1, us-east-2, us-west-2)
            table_prefix: Prefix for table names
        """
        self.region = region
        self.table_prefix = table_prefix
        self.dynamodb = boto3.resource('dynamodb', region_name=region)

        # Table references
        self.gpu_instances_table = self.dynamodb.Table(f"{table_prefix}-gpu-instances")
        self.routing_state_table = self.dynamodb.Table(f"{table_prefix}-routing-state")
        self.autoscaling_state_table = self.dynamodb.Table(f"{table_prefix}-autoscaling-state")
        self.cleanup_validation_table = self.dynamodb.Table(f"{table_prefix}-cleanup-validation")
        self.metrics_table = self.dynamodb.Table(f"{table_prefix}-metrics")

    # ==================== GPU Instances ====================

    def register_instance(
        self,
        instance_id: str,
        region: str,
        model_pool: str,
        ip_address: str,
        subnet_id: str,
        availability_zone: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Register a new GPU instance

        Args:
            instance_id: EC2 instance ID
            region: AWS region
            model_pool: Model pool name (model-a, model-b, model-c)
            ip_address: Private IP address
            subnet_id: Subnet ID
            availability_zone: AZ name
            metadata: Additional metadata

        Returns:
            True if successful
        """
        try:
            current_time = int(time.time())
            item = {
                'instance_id': instance_id,
                'region': region,
                'model_pool': model_pool,
                'state': 'launching',
                'queue_depth': 0,
                'last_heartbeat': current_time,
                'launch_time': current_time,
                'ip_address': ip_address,
                'subnet_id': subnet_id,
                'availability_zone': availability_zone,
                'metadata': json.dumps(metadata or {}),
                'ttl': current_time + 604800  # 7 days
            }

            self.gpu_instances_table.put_item(Item=item)
            logger.info(f"Registered instance {instance_id} in {region}")
            return True

        except ClientError as e:
            logger.error(f"Failed to register instance {instance_id}: {e}")
            return False

    def update_instance_state(
        self,
        instance_id: str,
        state: str,
        queue_depth: Optional[int] = None
    ) -> bool:
        """
        Update instance state

        Args:
            instance_id: EC2 instance ID
            state: New state (launching, available, draining, terminated, quarantined)
            queue_depth: Optional queue depth

        Returns:
            True if successful
        """
        try:
            update_expr = "SET #state = :state, last_heartbeat = :heartbeat"
            expr_values = {
                ':state': state,
                ':heartbeat': int(time.time())
            }
            expr_names = {'#state': 'state'}

            if queue_depth is not None:
                update_expr += ", queue_depth = :queue_depth"
                expr_values[':queue_depth'] = queue_depth

            self.gpu_instances_table.update_item(
                Key={'instance_id': instance_id},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_values,
                ExpressionAttributeNames=expr_names
            )

            logger.debug(f"Updated instance {instance_id} state to {state}")
            return True

        except ClientError as e:
            logger.error(f"Failed to update instance {instance_id}: {e}")
            return False

    def heartbeat(self, instance_id: str, queue_depth: int) -> bool:
        """
        Send heartbeat for instance

        Args:
            instance_id: EC2 instance ID
            queue_depth: Current queue depth

        Returns:
            True if successful
        """
        try:
            self.gpu_instances_table.update_item(
                Key={'instance_id': instance_id},
                UpdateExpression="SET last_heartbeat = :heartbeat, queue_depth = :queue_depth",
                ExpressionAttributeValues={
                    ':heartbeat': int(time.time()),
                    ':queue_depth': queue_depth
                }
            )
            return True

        except ClientError as e:
            logger.error(f"Heartbeat failed for {instance_id}: {e}")
            return False

    def get_instances_by_region(
        self,
        region: str,
        state: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all instances in a region

        Args:
            region: AWS region
            state: Optional state filter

        Returns:
            List of instance records
        """
        try:
            if state:
                response = self.gpu_instances_table.query(
                    IndexName='region-index',
                    KeyConditionExpression='region = :region',
                    FilterExpression='#state = :state',
                    ExpressionAttributeValues={
                        ':region': region,
                        ':state': state
                    },
                    ExpressionAttributeNames={'#state': 'state'}
                )
            else:
                response = self.gpu_instances_table.query(
                    IndexName='region-index',
                    KeyConditionExpression='region = :region',
                    ExpressionAttributeValues={':region': region}
                )

            return response.get('Items', [])

        except ClientError as e:
            logger.error(f"Failed to query instances in {region}: {e}")
            return []

    def get_instances_by_model_pool(self, model_pool: str) -> List[Dict[str, Any]]:
        """
        Get all instances for a model pool

        Args:
            model_pool: Model pool name

        Returns:
            List of instance records
        """
        try:
            response = self.gpu_instances_table.query(
                IndexName='model-pool-index',
                KeyConditionExpression='model_pool = :pool',
                ExpressionAttributeValues={':pool': model_pool}
            )
            return response.get('Items', [])

        except ClientError as e:
            logger.error(f"Failed to query model pool {model_pool}: {e}")
            return []

    # ==================== Routing State ====================

    def update_routing_state(
        self,
        instance_id: str,
        region: str,
        routing_score: float,
        queue_depth: int,
        avg_latency_ms: float,
        health_status: str,
        subnet_cidr: str
    ) -> bool:
        """
        Update routing state for an instance

        Args:
            instance_id: EC2 instance ID
            region: AWS region
            routing_score: Routing score (0-100, higher is better)
            queue_depth: Current queue depth
            avg_latency_ms: Average latency in milliseconds
            health_status: healthy, degraded, unhealthy
            subnet_cidr: Subnet CIDR for affinity routing

        Returns:
            True if successful
        """
        try:
            current_time = int(time.time())
            item = {
                'instance_id': instance_id,
                'region': region,
                'routing_score': int(routing_score),  # DynamoDB Number
                'queue_depth': queue_depth,
                'avg_latency_ms': int(avg_latency_ms),
                'health_status': health_status,
                'last_updated': current_time,
                'subnet_cidr': subnet_cidr,
                'ttl': current_time + 3600  # 1 hour
            }

            self.routing_state_table.put_item(Item=item)
            return True

        except ClientError as e:
            logger.error(f"Failed to update routing state for {instance_id}: {e}")
            return False

    def get_best_instances(
        self,
        region: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get best instances for routing in a region

        Args:
            region: AWS region
            limit: Maximum number of instances to return

        Returns:
            List of instance routing states, sorted by score (descending)
        """
        try:
            response = self.routing_state_table.query(
                IndexName='region-score-index',
                KeyConditionExpression='region = :region',
                ExpressionAttributeValues={':region': region},
                ScanIndexForward=False,  # Descending order
                Limit=limit
            )
            return response.get('Items', [])

        except ClientError as e:
            logger.error(f"Failed to get best instances in {region}: {e}")
            return []

    # ==================== Autoscaling State ====================

    def record_scaling_decision(
        self,
        model_pool: str,
        region: str,
        current_capacity: int,
        desired_capacity: int,
        min_capacity: int,
        max_capacity: int,
        current_rps: float,
        target_rps: float,
        scaling_action: str,
        reason: str
    ) -> bool:
        """
        Record an autoscaling decision

        Args:
            model_pool: Model pool name
            region: AWS region
            current_capacity: Current number of instances
            desired_capacity: Target number of instances
            min_capacity: Minimum allowed instances
            max_capacity: Maximum allowed instances
            current_rps: Current requests per second
            target_rps: Target RPS per instance
            scaling_action: scale-up, scale-down, none
            reason: Reason for decision

        Returns:
            True if successful
        """
        try:
            current_time = int(time.time())
            item = {
                'model_pool': model_pool,
                'timestamp': current_time,
                'region': region,
                'current_capacity': current_capacity,
                'desired_capacity': desired_capacity,
                'min_capacity': min_capacity,
                'max_capacity': max_capacity,
                'current_rps': int(current_rps * 100) / 100,  # Round to 2 decimals
                'target_rps': int(target_rps * 100) / 100,
                'scaling_action': scaling_action,
                'reason': reason,
                'ttl': current_time + 2592000  # 30 days
            }

            self.autoscaling_state_table.put_item(Item=item)
            logger.info(f"Recorded scaling decision for {model_pool}: {scaling_action}")
            return True

        except ClientError as e:
            logger.error(f"Failed to record scaling decision: {e}")
            return False

    def get_recent_scaling_decisions(
        self,
        model_pool: str,
        minutes: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get recent scaling decisions for a model pool

        Args:
            model_pool: Model pool name
            minutes: Look back period in minutes

        Returns:
            List of scaling decisions
        """
        try:
            cutoff_time = int(time.time()) - (minutes * 60)
            response = self.autoscaling_state_table.query(
                KeyConditionExpression='model_pool = :pool AND #ts > :cutoff',
                ExpressionAttributeValues={
                    ':pool': model_pool,
                    ':cutoff': cutoff_time
                },
                ExpressionAttributeNames={'#ts': 'timestamp'},
                ScanIndexForward=False  # Most recent first
            )
            return response.get('Items', [])

        except ClientError as e:
            logger.error(f"Failed to get scaling decisions: {e}")
            return []

    # ==================== Cleanup Validation ====================

    def record_cleanup_validation(
        self,
        instance_id: str,
        validation_status: str,
        gpu_memory_wiped: bool,
        system_memory_wiped: bool,
        enclave_stopped: bool,
        integrity_check: str,
        failure_reason: Optional[str] = None,
        quarantine_reason: Optional[str] = None
    ) -> bool:
        """
        Record cleanup validation result

        Args:
            instance_id: EC2 instance ID
            validation_status: pending, passed, failed
            gpu_memory_wiped: Whether GPU memory was wiped
            system_memory_wiped: Whether system memory was wiped
            enclave_stopped: Whether Nitro Enclave was stopped
            integrity_check: SHA256 hash of validation
            failure_reason: Reason if validation failed
            quarantine_reason: Reason for quarantine if failed

        Returns:
            True if successful
        """
        try:
            current_time = int(time.time())
            item = {
                'instance_id': instance_id,
                'validation_timestamp': current_time,
                'validation_status': validation_status,
                'gpu_memory_wiped': gpu_memory_wiped,
                'system_memory_wiped': system_memory_wiped,
                'enclave_stopped': enclave_stopped,
                'integrity_check': integrity_check,
                'ttl': current_time + 7776000  # 90 days
            }

            if failure_reason:
                item['failure_reason'] = failure_reason
            if quarantine_reason:
                item['quarantine_reason'] = quarantine_reason

            self.cleanup_validation_table.put_item(Item=item)
            logger.info(f"Recorded cleanup validation for {instance_id}: {validation_status}")
            return True

        except ClientError as e:
            logger.error(f"Failed to record cleanup validation: {e}")
            return False

    def get_failed_validations(
        self,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Get failed cleanup validations

        Args:
            hours: Look back period in hours

        Returns:
            List of failed validations
        """
        try:
            cutoff_time = int(time.time()) - (hours * 3600)
            response = self.cleanup_validation_table.query(
                IndexName='status-timestamp-index',
                KeyConditionExpression='validation_status = :status AND validation_timestamp > :cutoff',
                ExpressionAttributeValues={
                    ':status': 'failed',
                    ':cutoff': cutoff_time
                }
            )
            return response.get('Items', [])

        except ClientError as e:
            logger.error(f"Failed to get failed validations: {e}")
            return []

    # ==================== Metrics ====================

    def record_metric(
        self,
        metric_name: str,
        region: str,
        value: float,
        unit: str,
        dimensions: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Record a metric value

        Args:
            metric_name: Metric name (rps, queue_depth, model_load_time, etc.)
            region: AWS region
            value: Metric value
            unit: Unit (Count, Seconds, Milliseconds, etc.)
            dimensions: Additional dimensions

        Returns:
            True if successful
        """
        try:
            current_time = int(time.time())
            # Round to minute for better aggregation
            timestamp = (current_time // 60) * 60

            item = {
                'metric_name': metric_name,
                'timestamp': timestamp,
                'region': region,
                'value': int(value * 100) / 100,  # Round to 2 decimals
                'unit': unit,
                'dimensions': json.dumps(dimensions or {}),
                'ttl': current_time + 2592000  # 30 days
            }

            self.metrics_table.put_item(Item=item)
            return True

        except ClientError as e:
            logger.error(f"Failed to record metric {metric_name}: {e}")
            return False

    def get_metrics(
        self,
        metric_name: str,
        region: str,
        minutes: int = 60
    ) -> List[Dict[str, Any]]:
        """
        Get recent metric values

        Args:
            metric_name: Metric name
            region: AWS region
            minutes: Look back period in minutes

        Returns:
            List of metric records
        """
        try:
            cutoff_time = int(time.time()) - (minutes * 60)
            response = self.metrics_table.query(
                IndexName='region-timestamp-index',
                KeyConditionExpression='region = :region AND #ts > :cutoff',
                FilterExpression='metric_name = :metric',
                ExpressionAttributeValues={
                    ':region': region,
                    ':cutoff': cutoff_time,
                    ':metric': metric_name
                },
                ExpressionAttributeNames={'#ts': 'timestamp'}
            )
            return response.get('Items', [])

        except ClientError as e:
            logger.error(f"Failed to get metrics: {e}")
            return []

"""
Metrics Collector for Multi-Region GPU Cluster

Aggregates metrics from GPU instances and stores in DynamoDB
for monitoring and autoscaling decisions.
"""

import time
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from collections import defaultdict

from state_manager import StateManager

logger = logging.getLogger(__name__)


@dataclass
class MetricDataPoint:
    """Single metric data point"""
    metric_name: str
    timestamp: int
    value: float
    unit: str
    region: str
    dimensions: Dict[str, Any]


class MetricsCollector:
    """Collects and aggregates cluster metrics"""

    def __init__(self, region: str, table_prefix: str = "mrgc"):
        """
        Initialize metrics collector

        Args:
            region: AWS region
            table_prefix: DynamoDB table prefix
        """
        self.region = region
        self.state_mgr = StateManager(region, table_prefix)

    def record_rps(self, region: str, model_pool: str, rps: float) -> bool:
        """
        Record requests per second

        Args:
            region: AWS region
            model_pool: Model pool name
            rps: Requests per second

        Returns:
            True if successful
        """
        return self.state_mgr.record_metric(
            metric_name="rps",
            region=region,
            value=rps,
            unit="Count/Second",
            dimensions={"model_pool": model_pool}
        )

    def record_queue_depth(
        self,
        region: str,
        instance_id: str,
        queue_depth: int
    ) -> bool:
        """
        Record queue depth for an instance

        Args:
            region: AWS region
            instance_id: Instance ID
            queue_depth: Current queue depth

        Returns:
            True if successful
        """
        return self.state_mgr.record_metric(
            metric_name="queue_depth",
            region=region,
            value=float(queue_depth),
            unit="Count",
            dimensions={"instance_id": instance_id}
        )

    def record_model_load_time(
        self,
        region: str,
        model_pool: str,
        load_time_seconds: float
    ) -> bool:
        """
        Record model loading time

        Args:
            region: AWS region
            model_pool: Model pool name
            load_time_seconds: Time to load model in seconds

        Returns:
            True if successful
        """
        return self.state_mgr.record_metric(
            metric_name="model_load_time",
            region=region,
            value=load_time_seconds,
            unit="Seconds",
            dimensions={"model_pool": model_pool}
        )

    def record_inference_latency(
        self,
        region: str,
        model_pool: str,
        latency_ms: float,
        percentile: str = "p50"
    ) -> bool:
        """
        Record inference latency

        Args:
            region: AWS region
            model_pool: Model pool name
            latency_ms: Latency in milliseconds
            percentile: Percentile (p50, p95, p99)

        Returns:
            True if successful
        """
        return self.state_mgr.record_metric(
            metric_name=f"inference_latency_{percentile}",
            region=region,
            value=latency_ms,
            unit="Milliseconds",
            dimensions={"model_pool": model_pool}
        )

    def record_enclave_operation(
        self,
        region: str,
        operation: str,
        duration_ms: float,
        success: bool
    ) -> bool:
        """
        Record Nitro Enclave operation metrics

        Args:
            region: AWS region
            operation: Operation name (decrypt, encrypt, attestation)
            duration_ms: Duration in milliseconds
            success: Whether operation succeeded

        Returns:
            True if successful
        """
        return self.state_mgr.record_metric(
            metric_name=f"enclave_{operation}_duration",
            region=region,
            value=duration_ms,
            unit="Milliseconds",
            dimensions={
                "operation": operation,
                "success": str(success)
            }
        )

    def record_cleanup_validation(
        self,
        region: str,
        validation_status: str,
        duration_seconds: float
    ) -> bool:
        """
        Record cleanup validation metrics (Car Wash)

        Args:
            region: AWS region
            validation_status: passed, failed
            duration_seconds: Validation duration

        Returns:
            True if successful
        """
        return self.state_mgr.record_metric(
            metric_name="cleanup_validation_duration",
            region=region,
            value=duration_seconds,
            unit="Seconds",
            dimensions={"status": validation_status}
        )

    def get_cluster_rps(
        self,
        model_pool: Optional[str] = None,
        minutes: int = 5
    ) -> Dict[str, float]:
        """
        Get current RPS across all regions

        Args:
            model_pool: Optional model pool filter
            minutes: Look back period

        Returns:
            Dictionary of region -> RPS
        """
        regions = ["us-east-1", "us-east-2", "us-west-2"]
        rps_by_region = {}

        for region in regions:
            metrics = self.state_mgr.get_metrics(
                metric_name="rps",
                region=region,
                minutes=minutes
            )

            if model_pool:
                import json
                metrics = [
                    m for m in metrics
                    if json.loads(m.get('dimensions', '{}')).get('model_pool') == model_pool
                ]

            if metrics:
                # Average RPS over the period
                rps_by_region[region] = sum(m['value'] for m in metrics) / len(metrics)
            else:
                rps_by_region[region] = 0.0

        return rps_by_region

    def get_average_queue_depth(
        self,
        region: str,
        minutes: int = 5
    ) -> float:
        """
        Get average queue depth across all instances in a region

        Args:
            region: AWS region
            minutes: Look back period

        Returns:
            Average queue depth
        """
        metrics = self.state_mgr.get_metrics(
            metric_name="queue_depth",
            region=region,
            minutes=minutes
        )

        if not metrics:
            return 0.0

        # Group by instance and get latest value for each
        latest_by_instance = {}
        for m in metrics:
            import json
            instance_id = json.loads(m.get('dimensions', '{}')).get('instance_id')
            if instance_id:
                if instance_id not in latest_by_instance:
                    latest_by_instance[instance_id] = m
                elif m['timestamp'] > latest_by_instance[instance_id]['timestamp']:
                    latest_by_instance[instance_id] = m

        if not latest_by_instance:
            return 0.0

        # Average queue depth across instances
        total_queue = sum(m['value'] for m in latest_by_instance.values())
        return total_queue / len(latest_by_instance)

    def get_model_load_stats(
        self,
        model_pool: str,
        minutes: int = 60
    ) -> Dict[str, float]:
        """
        Get model loading statistics

        Args:
            model_pool: Model pool name
            minutes: Look back period

        Returns:
            Dictionary with min, max, avg, p50, p95, p99
        """
        metrics = []
        regions = ["us-east-1", "us-east-2", "us-west-2"]

        for region in regions:
            region_metrics = self.state_mgr.get_metrics(
                metric_name="model_load_time",
                region=region,
                minutes=minutes
            )

            import json
            region_metrics = [
                m for m in region_metrics
                if json.loads(m.get('dimensions', '{}')).get('model_pool') == model_pool
            ]

            metrics.extend(region_metrics)

        if not metrics:
            return {
                "min": 0.0,
                "max": 0.0,
                "avg": 0.0,
                "p50": 0.0,
                "p95": 0.0,
                "p99": 0.0,
                "count": 0
            }

        values = sorted([m['value'] for m in metrics])
        count = len(values)

        return {
            "min": values[0],
            "max": values[-1],
            "avg": sum(values) / count,
            "p50": values[int(count * 0.50)],
            "p95": values[int(count * 0.95)],
            "p99": values[int(count * 0.99)],
            "count": count
        }

    def get_inference_latency_stats(
        self,
        model_pool: str,
        minutes: int = 10
    ) -> Dict[str, float]:
        """
        Get inference latency statistics

        Args:
            model_pool: Model pool name
            minutes: Look back period

        Returns:
            Dictionary with p50, p95, p99 latencies
        """
        percentiles = ["p50", "p95", "p99"]
        stats = {}

        for percentile in percentiles:
            metrics = []
            regions = ["us-east-1", "us-east-2", "us-west-2"]

            for region in regions:
                region_metrics = self.state_mgr.get_metrics(
                    metric_name=f"inference_latency_{percentile}",
                    region=region,
                    minutes=minutes
                )

                import json
                region_metrics = [
                    m for m in region_metrics
                    if json.loads(m.get('dimensions', '{}')).get('model_pool') == model_pool
                ]

                metrics.extend(region_metrics)

            if metrics:
                # Average across the period
                stats[percentile] = sum(m['value'] for m in metrics) / len(metrics)
            else:
                stats[percentile] = 0.0

        return stats

    def get_cleanup_success_rate(
        self,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get cleanup validation success rate

        Args:
            hours: Look back period in hours

        Returns:
            Dictionary with success rate and counts
        """
        metrics = []
        regions = ["us-east-1", "us-east-2", "us-west-2"]

        for region in regions:
            region_metrics = self.state_mgr.get_metrics(
                metric_name="cleanup_validation_duration",
                region=region,
                minutes=hours * 60
            )
            metrics.extend(region_metrics)

        if not metrics:
            return {
                "success_rate": 100.0,
                "total_validations": 0,
                "passed": 0,
                "failed": 0
            }

        import json
        passed = sum(
            1 for m in metrics
            if json.loads(m.get('dimensions', '{}')).get('status') == 'passed'
        )
        failed = sum(
            1 for m in metrics
            if json.loads(m.get('dimensions', '{}')).get('status') == 'failed'
        )
        total = passed + failed

        return {
            "success_rate": (passed / total * 100) if total > 0 else 100.0,
            "total_validations": total,
            "passed": passed,
            "failed": failed
        }

    def get_cluster_health_summary(self) -> Dict[str, Any]:
        """
        Get overall cluster health summary

        Returns:
            Dictionary with cluster health metrics
        """
        # Get RPS by region
        rps_by_region = self.get_cluster_rps(minutes=5)
        total_rps = sum(rps_by_region.values())

        # Get queue depths
        queue_depths = {}
        for region in ["us-east-1", "us-east-2", "us-west-2"]:
            queue_depths[region] = self.get_average_queue_depth(region, minutes=5)

        avg_queue_depth = sum(queue_depths.values()) / len(queue_depths)

        # Get cleanup success rate
        cleanup_stats = self.get_cleanup_success_rate(hours=24)

        # Get instance counts by region
        instance_counts = {}
        for region in ["us-east-1", "us-east-2", "us-west-2"]:
            instances = self.state_mgr.get_instances_by_region(region, state="available")
            instance_counts[region] = len(instances)

        total_instances = sum(instance_counts.values())

        return {
            "timestamp": int(time.time()),
            "total_rps": total_rps,
            "rps_by_region": rps_by_region,
            "total_instances": total_instances,
            "instances_by_region": instance_counts,
            "avg_queue_depth": avg_queue_depth,
            "queue_depth_by_region": queue_depths,
            "cleanup_success_rate": cleanup_stats["success_rate"],
            "failed_validations_24h": cleanup_stats["failed"]
        }

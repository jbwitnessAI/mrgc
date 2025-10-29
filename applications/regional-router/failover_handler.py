"""
Failover Handler for Multi-Region GPU Cluster

Manages automatic failover when a region becomes unhealthy,
redirecting traffic to healthy regions.
"""

import boto3
import time
import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from enum import Enum

from health_monitor import HealthMonitor, HealthStatus, RegionHealth

logger = logging.getLogger(__name__)


class FailoverState(Enum):
    """Failover states"""
    NORMAL = "normal"
    DEGRADED = "degraded"
    FAILOVER_ACTIVE = "failover_active"
    RECOVERING = "recovering"


@dataclass
class FailoverEvent:
    """Failover event record"""
    timestamp: int
    from_region: str
    to_regions: List[str]
    reason: str
    affected_instances: int


@dataclass
class CrossRegionRoute:
    """Cross-region routing information"""
    source_region: str
    target_region: str
    latency_ms: int
    priority: int  # 1 = primary, 2 = secondary, etc.


class FailoverHandler:
    """Handles automatic cross-region failover"""

    # Cross-region latency matrix (approximate)
    REGION_LATENCY = {
        ("us-east-1", "us-east-2"): 15,
        ("us-east-1", "us-west-2"): 70,
        ("us-east-2", "us-east-1"): 15,
        ("us-east-2", "us-west-2"): 55,
        ("us-west-2", "us-east-1"): 70,
        ("us-west-2", "us-east-2"): 55,
    }

    def __init__(
        self,
        region: str,
        state_manager,
        metrics_collector,
        degraded_threshold: float = 0.5,  # 50% healthy
        unhealthy_threshold: float = 0.3,  # 30% healthy
        recovery_threshold: float = 0.8   # 80% healthy to recover
    ):
        """
        Initialize failover handler

        Args:
            region: AWS region
            state_manager: StateManager instance
            metrics_collector: MetricsCollector instance
            degraded_threshold: Percentage of healthy instances for degraded state
            unhealthy_threshold: Percentage of healthy instances for failover
            recovery_threshold: Percentage needed to recover from failover
        """
        self.region = region
        self.state_mgr = state_manager
        self.metrics_collector = metrics_collector
        self.degraded_threshold = degraded_threshold
        self.unhealthy_threshold = unhealthy_threshold
        self.recovery_threshold = recovery_threshold

        # Current failover state
        self.failover_state = FailoverState.NORMAL
        self.failover_events: List[FailoverEvent] = []

        # All regions in the cluster
        self.all_regions = ["us-east-1", "us-east-2", "us-west-2"]

    def evaluate_region_health(
        self,
        region_health: RegionHealth
    ) -> FailoverState:
        """
        Evaluate if failover is needed based on region health

        Args:
            region_health: RegionHealth object

        Returns:
            Recommended failover state
        """
        if region_health.total_instances == 0:
            return FailoverState.FAILOVER_ACTIVE

        healthy_ratio = region_health.healthy_instances / region_health.total_instances

        if healthy_ratio < self.unhealthy_threshold:
            return FailoverState.FAILOVER_ACTIVE
        elif healthy_ratio < self.degraded_threshold:
            return FailoverState.DEGRADED
        elif healthy_ratio >= self.recovery_threshold:
            return FailoverState.NORMAL
        else:
            # In between recovery threshold and normal - stay in current state
            return self.failover_state

    def get_failover_targets(self, source_region: str) -> List[CrossRegionRoute]:
        """
        Get prioritized list of failover target regions

        Args:
            source_region: Region that is failing

        Returns:
            List of CrossRegionRoute objects, sorted by priority
        """
        routes = []

        for target_region in self.all_regions:
            if target_region == source_region:
                continue

            latency = self.REGION_LATENCY.get(
                (source_region, target_region),
                100  # Default if not in matrix
            )

            # Priority based on latency (lower latency = higher priority)
            priority = 1 if latency < 30 else 2 if latency < 60 else 3

            routes.append(CrossRegionRoute(
                source_region=source_region,
                target_region=target_region,
                latency_ms=latency,
                priority=priority
            ))

        # Sort by priority (lower is better)
        routes.sort(key=lambda r: (r.priority, r.latency_ms))
        return routes

    def initiate_failover(
        self,
        region: str,
        region_health: RegionHealth
    ) -> bool:
        """
        Initiate failover from unhealthy region to healthy regions

        Args:
            region: Region to failover from
            region_health: Current region health

        Returns:
            True if failover initiated successfully
        """
        logger.warning(
            f"Initiating failover from {region}: "
            f"{region_health.healthy_instances}/{region_health.total_instances} healthy"
        )

        # Get failover target regions
        target_routes = self.get_failover_targets(region)

        # Check health of target regions
        healthy_targets = []
        for route in target_routes:
            # Get instances in target region
            target_instances = self.state_mgr.get_instances_by_region(
                route.target_region,
                state="available"
            )

            if len(target_instances) > 0:
                healthy_targets.append(route.target_region)
                logger.info(
                    f"Failover target: {route.target_region} "
                    f"({len(target_instances)} instances, {route.latency_ms}ms latency)"
                )

        if not healthy_targets:
            logger.error("No healthy failover targets available!")
            return False

        # Record failover event
        failover_event = FailoverEvent(
            timestamp=int(time.time()),
            from_region=region,
            to_regions=healthy_targets,
            reason=region_health.degraded_reason or "Region unhealthy",
            affected_instances=region_health.total_instances
        )
        self.failover_events.append(failover_event)

        # Update failover state
        self.failover_state = FailoverState.FAILOVER_ACTIVE

        # Record metric
        self.metrics_collector.record_metric(
            metric_name="failover_event",
            region=region,
            value=1.0,
            unit="Count",
            dimensions={
                "from_region": region,
                "to_regions": ",".join(healthy_targets)
            }
        )

        logger.warning(
            f"Failover active: {region} -> {healthy_targets} "
            f"(expected latency increase: {target_routes[0].latency_ms}ms)"
        )

        # Trigger auto-scaling in target regions to handle additional load
        self._trigger_failover_scaling(healthy_targets, region_health.total_instances)

        return True

    def check_recovery(self, region_health: RegionHealth) -> bool:
        """
        Check if region has recovered and can resume normal operations

        Args:
            region_health: Current region health

        Returns:
            True if recovery completed
        """
        if self.failover_state != FailoverState.FAILOVER_ACTIVE:
            return False

        healthy_ratio = (
            region_health.healthy_instances / region_health.total_instances
            if region_health.total_instances > 0 else 0
        )

        if healthy_ratio >= self.recovery_threshold:
            logger.info(
                f"Region {self.region} recovering: "
                f"{region_health.healthy_instances}/{region_health.total_instances} healthy"
            )

            self.failover_state = FailoverState.RECOVERING

            # Record recovery metric
            self.metrics_collector.record_metric(
                metric_name="failover_recovery",
                region=self.region,
                value=1.0,
                unit="Count",
                dimensions={"healthy_ratio": f"{healthy_ratio:.2f}"}
            )

            return True

        return False

    def complete_recovery(self) -> bool:
        """
        Complete recovery and return to normal state

        Returns:
            True if successful
        """
        if self.failover_state != FailoverState.RECOVERING:
            return False

        logger.info(f"Region {self.region} recovered - returning to normal state")

        self.failover_state = FailoverState.NORMAL

        # Record completion metric
        self.metrics_collector.record_metric(
            metric_name="failover_complete",
            region=self.region,
            value=1.0,
            unit="Count",
            dimensions={"state": "recovered"}
        )

        return True

    def get_routing_preference(self) -> Dict[str, int]:
        """
        Get routing preference weights based on failover state

        Returns:
            Dictionary of region -> weight (0-100)
        """
        if self.failover_state == FailoverState.NORMAL:
            # Normal state - prefer local region
            return {
                self.region: 100,
                **{r: 10 for r in self.all_regions if r != self.region}
            }

        elif self.failover_state == FailoverState.DEGRADED:
            # Degraded - reduce local preference
            return {
                self.region: 70,
                **{r: 30 for r in self.all_regions if r != self.region}
            }

        elif self.failover_state == FailoverState.FAILOVER_ACTIVE:
            # Failover active - avoid local region
            failover_targets = self.get_failover_targets(self.region)
            return {
                self.region: 5,  # Minimal traffic to failed region
                failover_targets[0].target_region: 80,  # Primary failover target
                failover_targets[1].target_region if len(failover_targets) > 1 else self.region: 15
            }

        elif self.failover_state == FailoverState.RECOVERING:
            # Recovering - gradually increase local traffic
            return {
                self.region: 50,
                **{r: 25 for r in self.all_regions if r != self.region}
            }

        else:
            # Unknown state - default to local
            return {self.region: 100}

    def _trigger_failover_scaling(
        self,
        target_regions: List[str],
        additional_capacity_needed: int
    ) -> None:
        """
        Trigger auto-scaling in target regions to handle failover traffic

        Args:
            target_regions: List of regions to scale up
            additional_capacity_needed: Number of additional instances needed
        """
        # Distribute capacity across target regions
        capacity_per_region = additional_capacity_needed // len(target_regions)

        for target_region in target_regions:
            logger.info(
                f"Requesting {capacity_per_region} additional instances "
                f"in {target_region} for failover"
            )

            # Record scaling request
            self.state_mgr.record_scaling_decision(
                model_pool="all",  # Affects all model pools
                region=target_region,
                current_capacity=0,  # Will be filled by autoscaler
                desired_capacity=capacity_per_region,
                min_capacity=0,
                max_capacity=100,
                current_rps=0.0,
                target_rps=1.5,
                scaling_action="scale-up",
                reason=f"Failover from {self.region}"
            )

    def get_failover_summary(self) -> Dict:
        """
        Get summary of current failover state

        Returns:
            Dictionary with failover information
        """
        recent_events = [
            e for e in self.failover_events
            if e.timestamp > int(time.time()) - 3600  # Last hour
        ]

        return {
            "current_state": self.failover_state.value,
            "region": self.region,
            "recent_events_count": len(recent_events),
            "routing_preference": self.get_routing_preference(),
            "last_failover": (
                recent_events[-1].timestamp if recent_events else None
            )
        }

    def simulate_regional_failure(self, region: str) -> None:
        """
        Simulate a regional failure for testing

        Args:
            region: Region to simulate failure for
        """
        logger.warning(f"SIMULATION: Regional failure for {region}")

        # Create mock region health showing failure
        from health_monitor import RegionHealth

        mock_health = RegionHealth(
            region=region,
            status=HealthStatus.UNHEALTHY,
            healthy_instances=1,
            total_instances=10,
            avg_response_time_ms=9999.0,
            last_check=int(time.time()),
            degraded_reason="Simulated failure"
        )

        # Initiate failover
        self.initiate_failover(region, mock_health)

    def run_failover_monitor_loop(
        self,
        health_monitor: HealthMonitor,
        check_interval: int = 60
    ) -> None:
        """
        Run continuous failover monitoring loop

        Args:
            health_monitor: HealthMonitor instance
            check_interval: Seconds between checks
        """
        logger.info(f"Starting failover monitor for {self.region}")

        while True:
            try:
                # Check region health
                instance_healths = health_monitor.check_all_instances()
                region_health = health_monitor.calculate_region_health(instance_healths)

                # Evaluate if failover needed
                recommended_state = self.evaluate_region_health(region_health)

                # Handle state transitions
                if recommended_state == FailoverState.FAILOVER_ACTIVE:
                    if self.failover_state != FailoverState.FAILOVER_ACTIVE:
                        self.initiate_failover(self.region, region_health)

                elif recommended_state == FailoverState.NORMAL:
                    if self.failover_state == FailoverState.RECOVERING:
                        self.complete_recovery()
                    elif self.failover_state == FailoverState.FAILOVER_ACTIVE:
                        # Start recovery
                        self.check_recovery(region_health)

                elif recommended_state == FailoverState.DEGRADED:
                    if self.failover_state == FailoverState.NORMAL:
                        self.failover_state = FailoverState.DEGRADED
                        logger.warning(f"Region {self.region} entering degraded state")

                # Log current state
                if self.failover_state != FailoverState.NORMAL:
                    logger.info(
                        f"Failover state: {self.failover_state.value}, "
                        f"Region health: {region_health.status.value}"
                    )

                time.sleep(check_interval)

            except Exception as e:
                logger.error(f"Failover monitor error: {e}", exc_info=True)
                time.sleep(5)

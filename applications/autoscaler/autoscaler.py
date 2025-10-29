#!/usr/bin/env python3
"""
Auto-Scaler for Multi-Region GPU Cluster

Automatically scales GPU instances based on requests per second (RPS).

Scaling Algorithm:
- Target: 10-15 RPS per GPU instance
- Scale up: If current RPS > target × instance count for 2+ minutes
- Scale down: If current RPS < (target × 0.5) × instance count for 10+ minutes
- Min instances: 2 per region (for HA)
- Max instances: 20 per region (configurable)

This runs as a Lambda function or ECS task that executes every minute.
"""

import boto3
import logging
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import sys

# Import from global-state
sys.path.append('/opt/mrgc/applications/global-state')
from state_manager import StateManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[AUTOSCALER] %(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AutoScaler:
    """Auto-scales GPU instances based on RPS"""

    def __init__(self, region: str):
        """
        Initialize auto-scaler

        Args:
            region: AWS region
        """
        logger.info(f"Initializing auto-scaler for {region}")

        self.region = region

        # AWS clients
        self.ec2 = boto3.client('ec2', region_name=region)
        self.cloudwatch = boto3.client('cloudwatch', region_name=region)

        # State manager for DynamoDB
        self.state_mgr = StateManager(region=region)

        # Scaling configuration
        self.target_rps_per_instance = 12.5  # Target: 10-15 RPS per instance
        self.min_instances = 2  # Minimum for HA
        self.max_instances = 20  # Maximum per region
        self.scale_up_threshold_minutes = 2  # Scale up after 2 minutes
        self.scale_down_threshold_minutes = 10  # Scale down after 10 minutes
        self.cooldown_period_seconds = 300  # 5 minute cooldown

    def get_current_rps(self) -> float:
        """
        Get current RPS from CloudWatch

        Returns:
            Current RPS (requests per second)
        """
        try:
            # Query CloudWatch for NLB request count
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=5)

            response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/NetworkELB',
                MetricName='ActiveFlowCount',
                Dimensions=[
                    {
                        'Name': 'LoadBalancer',
                        'Value': f'net/mrgc-nlb-{self.region}/...'  # Set from config
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=60,
                Statistics=['Average']
            )

            datapoints = response.get('Datapoints', [])

            if not datapoints:
                logger.warning("No CloudWatch data available")
                return 0.0

            # Calculate average RPS from last 5 minutes
            total_requests = sum(dp['Average'] for dp in datapoints)
            avg_rps = total_requests / (len(datapoints) * 60)  # Convert to RPS

            logger.info(f"Current RPS: {avg_rps:.2f}")

            return avg_rps

        except Exception as e:
            logger.error(f"Error getting RPS from CloudWatch: {e}")
            return 0.0

    def get_current_instance_count(self) -> int:
        """
        Get current number of GPU instances

        Returns:
            Number of running instances
        """
        try:
            # Query DynamoDB for instances in this region
            instances = self.state_mgr.list_gpu_instances(
                filters={'region': self.region, 'status': 'ready'}
            )

            count = len(instances)
            logger.info(f"Current instance count: {count}")

            return count

        except Exception as e:
            logger.error(f"Error getting instance count: {e}")
            return 0

    def get_scaling_state(self) -> Dict:
        """
        Get current scaling state from DynamoDB

        Returns:
            Scaling state dict
        """
        try:
            state = self.state_mgr.get_autoscaling_state(self.region)

            if not state:
                # Create initial state
                state = {
                    'region': self.region,
                    'desired_capacity': self.min_instances,
                    'last_scale_action': None,
                    'last_scale_time': 0,
                    'high_rps_since': None,
                    'low_rps_since': None
                }
                self.state_mgr.update_autoscaling_state(self.region, state)

            return state

        except Exception as e:
            logger.error(f"Error getting scaling state: {e}")
            return {}

    def should_scale_up(
        self,
        current_rps: float,
        current_count: int,
        scaling_state: Dict
    ) -> bool:
        """
        Check if we should scale up

        Scale up if:
        - RPS > target × instance count
        - Condition persists for 2+ minutes
        - Not in cooldown period

        Args:
            current_rps: Current RPS
            current_count: Current instance count
            scaling_state: Current scaling state

        Returns:
            True if should scale up
        """
        # Check if at max capacity
        if current_count >= self.max_instances:
            logger.info("At max capacity, cannot scale up")
            return False

        # Check cooldown
        last_scale_time = scaling_state.get('last_scale_time', 0)
        if time.time() - last_scale_time < self.cooldown_period_seconds:
            logger.info("In cooldown period, skipping scale up")
            return False

        # Calculate threshold
        target_rps = self.target_rps_per_instance * current_count
        scale_up_threshold = target_rps * 1.2  # 20% buffer

        if current_rps > scale_up_threshold:
            # Check duration
            high_rps_since = scaling_state.get('high_rps_since')

            if not high_rps_since:
                # Start tracking
                logger.info(f"RPS {current_rps:.2f} > threshold {scale_up_threshold:.2f}, starting timer")
                scaling_state['high_rps_since'] = time.time()
                self.state_mgr.update_autoscaling_state(self.region, scaling_state)
                return False

            # Check if duration exceeded
            duration = time.time() - high_rps_since
            if duration >= self.scale_up_threshold_minutes * 60:
                logger.info(f"High RPS for {duration:.0f}s, scaling up")
                return True
            else:
                logger.info(f"High RPS for {duration:.0f}s (need {self.scale_up_threshold_minutes * 60}s)")
                return False
        else:
            # Reset timer
            if scaling_state.get('high_rps_since'):
                scaling_state['high_rps_since'] = None
                self.state_mgr.update_autoscaling_state(self.region, scaling_state)

            return False

    def should_scale_down(
        self,
        current_rps: float,
        current_count: int,
        scaling_state: Dict
    ) -> bool:
        """
        Check if we should scale down

        Scale down if:
        - RPS < (target × 0.5) × instance count
        - Condition persists for 10+ minutes
        - Not in cooldown period
        - Above minimum

        Args:
            current_rps: Current RPS
            current_count: Current instance count
            scaling_state: Current scaling state

        Returns:
            True if should scale down
        """
        # Check if at min capacity
        if current_count <= self.min_instances:
            logger.info("At min capacity, cannot scale down")
            return False

        # Check cooldown
        last_scale_time = scaling_state.get('last_scale_time', 0)
        if time.time() - last_scale_time < self.cooldown_period_seconds:
            logger.info("In cooldown period, skipping scale down")
            return False

        # Calculate threshold
        target_rps = self.target_rps_per_instance * current_count
        scale_down_threshold = target_rps * 0.5  # 50% of target

        if current_rps < scale_down_threshold:
            # Check duration
            low_rps_since = scaling_state.get('low_rps_since')

            if not low_rps_since:
                # Start tracking
                logger.info(f"RPS {current_rps:.2f} < threshold {scale_down_threshold:.2f}, starting timer")
                scaling_state['low_rps_since'] = time.time()
                self.state_mgr.update_autoscaling_state(self.region, scaling_state)
                return False

            # Check if duration exceeded
            duration = time.time() - low_rps_since
            if duration >= self.scale_down_threshold_minutes * 60:
                logger.info(f"Low RPS for {duration:.0f}s, scaling down")
                return True
            else:
                logger.info(f"Low RPS for {duration:.0f}s (need {self.scale_down_threshold_minutes * 60}s)")
                return False
        else:
            # Reset timer
            if scaling_state.get('low_rps_since'):
                scaling_state['low_rps_since'] = None
                self.state_mgr.update_autoscaling_state(self.region, scaling_state)

            return False

    def scale_up(self, current_count: int) -> bool:
        """
        Scale up by 1 instance

        Args:
            current_count: Current instance count

        Returns:
            True if successful
        """
        logger.info(f"Scaling up from {current_count} to {current_count + 1}")

        try:
            # In production, launch new EC2 instance with:
            # - AMI with Nitro Enclave support
            # - g6e.2xlarge instance type
            # - FSx Lustre mounted
            # - Parent instance application
            # - Nitro enclave running
            #
            # response = self.ec2.run_instances(
            #     ImageId='ami-xxxxx',
            #     InstanceType='g6e.2xlarge',
            #     MinCount=1,
            #     MaxCount=1,
            #     ...
            # )

            # Update scaling state
            scaling_state = self.get_scaling_state()
            scaling_state['desired_capacity'] = current_count + 1
            scaling_state['last_scale_action'] = 'scale_up'
            scaling_state['last_scale_time'] = time.time()
            scaling_state['high_rps_since'] = None
            scaling_state['low_rps_since'] = None

            self.state_mgr.update_autoscaling_state(self.region, scaling_state)

            logger.info("✓ Scale up initiated")
            return True

        except Exception as e:
            logger.error(f"Error scaling up: {e}", exc_info=True)
            return False

    def scale_down(self, current_count: int) -> bool:
        """
        Scale down by 1 instance

        Args:
            current_count: Current instance count

        Returns:
            True if successful
        """
        logger.info(f"Scaling down from {current_count} to {current_count - 1}")

        try:
            # Find instance to terminate (select least-loaded)
            instances = self.state_mgr.list_gpu_instances(
                filters={'region': self.region, 'status': 'ready'}
            )

            if not instances:
                logger.warning("No instances to terminate")
                return False

            # Select instance with lowest routing score
            instance_to_terminate = min(instances, key=lambda x: x.get('routing_score', 0))

            logger.info(f"Terminating instance: {instance_to_terminate['instance_id']}")

            # In production, terminate EC2 instance:
            # self.ec2.terminate_instances(
            #     InstanceIds=[instance_to_terminate['instance_id']]
            # )

            # Update DynamoDB
            self.state_mgr.delete_gpu_instance(instance_to_terminate['instance_id'])

            # Update scaling state
            scaling_state = self.get_scaling_state()
            scaling_state['desired_capacity'] = current_count - 1
            scaling_state['last_scale_action'] = 'scale_down'
            scaling_state['last_scale_time'] = time.time()
            scaling_state['high_rps_since'] = None
            scaling_state['low_rps_since'] = None

            self.state_mgr.update_autoscaling_state(self.region, scaling_state)

            logger.info("✓ Scale down initiated")
            return True

        except Exception as e:
            logger.error(f"Error scaling down: {e}", exc_info=True)
            return False

    def run(self):
        """
        Run auto-scaling check

        This is called periodically (every minute)
        """
        logger.info("Running auto-scaling check")

        try:
            # Get current metrics
            current_rps = self.get_current_rps()
            current_count = self.get_current_instance_count()
            scaling_state = self.get_scaling_state()

            logger.info(f"Metrics: RPS={current_rps:.2f}, Instances={current_count}")

            # Check if should scale
            if self.should_scale_up(current_rps, current_count, scaling_state):
                self.scale_up(current_count)
            elif self.should_scale_down(current_rps, current_count, scaling_state):
                self.scale_down(current_count)
            else:
                logger.info("No scaling action needed")

        except Exception as e:
            logger.error(f"Error in auto-scaling check: {e}", exc_info=True)


def lambda_handler(event, context):
    """
    AWS Lambda handler

    This function is invoked every minute by EventBridge
    """
    # Get region from environment or event
    region = event.get('region', 'us-east-1')

    # Create and run auto-scaler
    scaler = AutoScaler(region=region)
    scaler.run()

    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'Auto-scaling check complete'})
    }


def main():
    """Main entry point for testing"""
    import argparse

    parser = argparse.ArgumentParser(description="GPU Cluster Auto-Scaler")
    parser.add_argument('--region', default='us-east-1', help='AWS region')
    args = parser.parse_args()

    scaler = AutoScaler(region=args.region)
    scaler.run()


if __name__ == '__main__':
    main()

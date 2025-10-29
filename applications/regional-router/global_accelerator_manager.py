"""
Global Accelerator Manager for Multi-Region GPU Cluster

Manages AWS Global Accelerator traffic dial adjustments during failover events.
Integrates with FailoverHandler to coordinate traffic routing.
"""

import boto3
import logging
from typing import Dict, List, Optional
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class GlobalAcceleratorManager:
    """Manages Global Accelerator traffic dials for failover"""

    def __init__(
        self,
        accelerator_arn: str,
        region_endpoint_group_arns: Dict[str, str]
    ):
        """
        Initialize Global Accelerator manager

        Args:
            accelerator_arn: ARN of the Global Accelerator
            region_endpoint_group_arns: Map of region -> endpoint group ARN
        """
        self.accelerator_arn = accelerator_arn
        self.region_endpoint_group_arns = region_endpoint_group_arns

        # Global Accelerator client (global service, use us-west-2)
        self.client = boto3.client('globalaccelerator', region_name='us-west-2')

    def set_traffic_dial(self, region: str, percentage: int) -> bool:
        """
        Set traffic dial percentage for a region

        Args:
            region: AWS region
            percentage: Traffic dial percentage (0-100)

        Returns:
            True if successful
        """
        if region not in self.region_endpoint_group_arns:
            logger.error(f"Unknown region: {region}")
            return False

        endpoint_group_arn = self.region_endpoint_group_arns[region]

        if percentage < 0 or percentage > 100:
            logger.error(f"Invalid traffic dial percentage: {percentage}")
            return False

        try:
            self.client.update_endpoint_group(
                EndpointGroupArn=endpoint_group_arn,
                TrafficDialPercentage=percentage
            )

            logger.info(f"Set traffic dial for {region} to {percentage}%")
            return True

        except ClientError as e:
            logger.error(f"Failed to set traffic dial for {region}: {e}")
            return False

    def get_traffic_dials(self) -> Dict[str, int]:
        """
        Get current traffic dial percentages for all regions

        Returns:
            Map of region -> traffic dial percentage
        """
        traffic_dials = {}

        for region, endpoint_group_arn in self.region_endpoint_group_arns.items():
            try:
                response = self.client.describe_endpoint_group(
                    EndpointGroupArn=endpoint_group_arn
                )

                endpoint_group = response['EndpointGroup']
                traffic_dials[region] = endpoint_group['TrafficDialPercentage']

            except ClientError as e:
                logger.error(f"Failed to get traffic dial for {region}: {e}")
                traffic_dials[region] = None

        return traffic_dials

    def initiate_failover(
        self,
        failed_region: str,
        target_regions: List[str]
    ) -> bool:
        """
        Initiate failover by adjusting traffic dials

        Args:
            failed_region: Region that is failing
            target_regions: List of regions to receive traffic

        Returns:
            True if successful
        """
        logger.warning(f"Initiating Global Accelerator failover from {failed_region}")

        # Set failed region to minimal traffic (0%)
        success = self.set_traffic_dial(failed_region, 0)

        if not success:
            logger.error(f"Failed to set traffic dial for {failed_region}")
            return False

        # Set target regions to full traffic (100%)
        for target_region in target_regions:
            success = self.set_traffic_dial(target_region, 100)
            if not success:
                logger.error(f"Failed to set traffic dial for {target_region}")

        logger.info(
            f"Global Accelerator failover complete: "
            f"{failed_region} -> {target_regions}"
        )

        return True

    def initiate_recovery(
        self,
        recovering_region: str,
        percentage: int = 50
    ) -> bool:
        """
        Begin gradual recovery by increasing traffic dial

        Args:
            recovering_region: Region that is recovering
            percentage: Initial traffic dial percentage

        Returns:
            True if successful
        """
        logger.info(
            f"Initiating Global Accelerator recovery for {recovering_region} "
            f"at {percentage}%"
        )

        return self.set_traffic_dial(recovering_region, percentage)

    def complete_recovery(self, region: str) -> bool:
        """
        Complete recovery by restoring full traffic

        Args:
            region: Region that has recovered

        Returns:
            True if successful
        """
        logger.info(f"Completing Global Accelerator recovery for {region}")

        return self.set_traffic_dial(region, 100)

    def get_endpoint_health(self) -> Dict[str, Dict]:
        """
        Get health status of all endpoints

        Returns:
            Map of region -> endpoint health info
        """
        endpoint_health = {}

        for region, endpoint_group_arn in self.region_endpoint_group_arns.items():
            try:
                response = self.client.describe_endpoint_group(
                    EndpointGroupArn=endpoint_group_arn
                )

                endpoint_group = response['EndpointGroup']
                endpoints = endpoint_group.get('EndpointDescriptions', [])

                if endpoints:
                    endpoint = endpoints[0]  # We have 1 NLB per region
                    endpoint_health[region] = {
                        'health_state': endpoint.get('HealthState', 'UNKNOWN'),
                        'health_reason': endpoint.get('HealthReason', ''),
                        'endpoint_id': endpoint.get('EndpointId', ''),
                        'traffic_dial': endpoint_group['TrafficDialPercentage']
                    }
                else:
                    endpoint_health[region] = {
                        'health_state': 'NO_ENDPOINTS',
                        'health_reason': 'No endpoints configured',
                        'endpoint_id': None,
                        'traffic_dial': endpoint_group['TrafficDialPercentage']
                    }

            except ClientError as e:
                logger.error(f"Failed to get endpoint health for {region}: {e}")
                endpoint_health[region] = {
                    'health_state': 'ERROR',
                    'health_reason': str(e),
                    'endpoint_id': None,
                    'traffic_dial': None
                }

        return endpoint_health

    def get_summary(self) -> Dict:
        """
        Get summary of Global Accelerator status

        Returns:
            Summary dictionary
        """
        try:
            response = self.client.describe_accelerator(
                AcceleratorArn=self.accelerator_arn
            )

            accelerator = response['Accelerator']
            traffic_dials = self.get_traffic_dials()
            endpoint_health = self.get_endpoint_health()

            return {
                'name': accelerator['Name'],
                'status': accelerator['Status'],
                'enabled': accelerator['Enabled'],
                'dns_name': accelerator['DnsName'],
                'static_ips': [
                    ip for ip_set in accelerator['IpSets']
                    for ip in ip_set['IpAddresses']
                ],
                'traffic_dials': traffic_dials,
                'endpoint_health': endpoint_health
            }

        except ClientError as e:
            logger.error(f"Failed to get accelerator summary: {e}")
            return {
                'error': str(e)
            }

    def enable_accelerator(self) -> bool:
        """
        Enable the Global Accelerator

        Returns:
            True if successful
        """
        try:
            self.client.update_accelerator(
                AcceleratorArn=self.accelerator_arn,
                Enabled=True
            )

            logger.info("Global Accelerator enabled")
            return True

        except ClientError as e:
            logger.error(f"Failed to enable Global Accelerator: {e}")
            return False

    def disable_accelerator(self) -> bool:
        """
        Disable the Global Accelerator

        Returns:
            True if successful
        """
        try:
            self.client.update_accelerator(
                AcceleratorArn=self.accelerator_arn,
                Enabled=False
            )

            logger.warning("Global Accelerator disabled")
            return True

        except ClientError as e:
            logger.error(f"Failed to disable Global Accelerator: {e}")
            return False

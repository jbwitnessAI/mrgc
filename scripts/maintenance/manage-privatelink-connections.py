#!/usr/bin/env python3
"""
Manage PrivateLink Connection Requests

This script helps approve/reject VPC endpoint connection requests
for the Multi-Region GPU Cluster.
"""

import boto3
import argparse
import sys
from datetime import datetime
from typing import List, Dict, Optional


class PrivateLinkManager:
    """Manages VPC Endpoint Service connections"""

    def __init__(self, region: str):
        """
        Initialize manager

        Args:
            region: AWS region
        """
        self.region = region
        self.ec2 = boto3.client('ec2', region_name=region)

    def list_endpoint_services(self) -> List[Dict]:
        """
        List all VPC Endpoint Services in the region

        Returns:
            List of service configurations
        """
        try:
            response = self.ec2.describe_vpc_endpoint_service_configurations()
            return response.get('ServiceConfigurations', [])

        except Exception as e:
            print(f"Error listing services: {e}")
            return []

    def get_service_by_name(self, service_name: str) -> Optional[Dict]:
        """
        Get VPC Endpoint Service by name

        Args:
            service_name: Service name (e.g., com.amazonaws.vpce.xxx.vpce-svc-yyy)

        Returns:
            Service configuration dict or None
        """
        services = self.list_endpoint_services()

        for service in services:
            if service['ServiceName'] == service_name:
                return service

        return None

    def list_connection_requests(
        self,
        service_id: str,
        state: Optional[str] = None
    ) -> List[Dict]:
        """
        List VPC endpoint connection requests

        Args:
            service_id: VPC Endpoint Service ID (vpce-svc-xxx)
            state: Filter by state (PendingAcceptance, Accepted, Rejected)

        Returns:
            List of connection requests
        """
        try:
            kwargs = {'ServiceId': service_id}
            if state:
                kwargs['Filters'] = [{'Name': 'vpc-endpoint-state', 'Values': [state]}]

            response = self.ec2.describe_vpc_endpoint_connections(**kwargs)
            return response.get('VpcEndpointConnections', [])

        except Exception as e:
            print(f"Error listing connection requests: {e}")
            return []

    def approve_connection(
        self,
        service_id: str,
        vpc_endpoint_id: str
    ) -> bool:
        """
        Approve a VPC endpoint connection request

        Args:
            service_id: VPC Endpoint Service ID
            vpc_endpoint_id: VPC Endpoint ID to approve

        Returns:
            True if successful
        """
        try:
            self.ec2.accept_vpc_endpoint_connections(
                ServiceId=service_id,
                VpcEndpointIds=[vpc_endpoint_id]
            )

            print(f"✅ Approved connection: {vpc_endpoint_id}")
            return True

        except Exception as e:
            print(f"❌ Failed to approve {vpc_endpoint_id}: {e}")
            return False

    def reject_connection(
        self,
        service_id: str,
        vpc_endpoint_id: str
    ) -> bool:
        """
        Reject a VPC endpoint connection request

        Args:
            service_id: VPC Endpoint Service ID
            vpc_endpoint_id: VPC Endpoint ID to reject

        Returns:
            True if successful
        """
        try:
            self.ec2.reject_vpc_endpoint_connections(
                ServiceId=service_id,
                VpcEndpointIds=[vpc_endpoint_id]
            )

            print(f"🚫 Rejected connection: {vpc_endpoint_id}")
            return True

        except Exception as e:
            print(f"❌ Failed to reject {vpc_endpoint_id}: {e}")
            return False

    def get_endpoint_details(self, vpc_endpoint_id: str) -> Optional[Dict]:
        """
        Get VPC endpoint details

        Args:
            vpc_endpoint_id: VPC Endpoint ID

        Returns:
            Endpoint details or None
        """
        try:
            response = self.ec2.describe_vpc_endpoints(
                VpcEndpointIds=[vpc_endpoint_id]
            )

            endpoints = response.get('VpcEndpoints', [])
            return endpoints[0] if endpoints else None

        except Exception as e:
            print(f"Error getting endpoint details: {e}")
            return None


def list_pending_requests(manager: PrivateLinkManager, service_id: str):
    """List all pending connection requests"""
    print(f"\n🔍 Pending connection requests for {service_id}:\n")

    requests = manager.list_connection_requests(
        service_id,
        state='PendingAcceptance'
    )

    if not requests:
        print("  No pending requests.")
        return

    for req in requests:
        endpoint_id = req['VpcEndpointId']
        owner = req['VpcEndpointOwner']
        created = req.get('CreationTimestamp', 'Unknown')

        print(f"  • Endpoint: {endpoint_id}")
        print(f"    Owner: {owner}")
        print(f"    Created: {created}")
        print(f"    State: {req.get('VpcEndpointState', 'Unknown')}")
        print()


def list_all_connections(manager: PrivateLinkManager, service_id: str):
    """List all connections (all states)"""
    print(f"\n📊 All connections for {service_id}:\n")

    requests = manager.list_connection_requests(service_id)

    if not requests:
        print("  No connections found.")
        return

    for req in requests:
        endpoint_id = req['VpcEndpointId']
        owner = req['VpcEndpointOwner']
        state = req.get('VpcEndpointState', 'Unknown')
        created = req.get('CreationTimestamp', 'Unknown')

        status_emoji = {
            'Available': '✅',
            'PendingAcceptance': '⏳',
            'Rejected': '🚫',
            'Deleting': '🗑️'
        }.get(state, '❓')

        print(f"  {status_emoji} {endpoint_id}")
        print(f"    Owner: {owner}")
        print(f"    State: {state}")
        print(f"    Created: {created}")
        print()


def approve_request(
    manager: PrivateLinkManager,
    service_id: str,
    vpc_endpoint_id: str
):
    """Approve a specific connection request"""
    print(f"\n⏳ Approving connection request...\n")

    # Get endpoint details
    endpoint = manager.get_endpoint_details(vpc_endpoint_id)
    if endpoint:
        print(f"  Endpoint ID: {vpc_endpoint_id}")
        print(f"  Owner: {endpoint.get('OwnerId', 'Unknown')}")
        print(f"  VPC: {endpoint.get('VpcId', 'Unknown')}")
        print()

    # Confirm
    confirm = input("Approve this request? [y/N]: ")
    if confirm.lower() != 'y':
        print("❌ Cancelled.")
        return

    # Approve
    success = manager.approve_connection(service_id, vpc_endpoint_id)

    if success:
        print("\n✅ Connection approved successfully!")
        print(f"\nNotify tenant that their VPC endpoint {vpc_endpoint_id} is now active.")


def reject_request(
    manager: PrivateLinkManager,
    service_id: str,
    vpc_endpoint_id: str
):
    """Reject a specific connection request"""
    print(f"\n⏳ Rejecting connection request...\n")

    # Get endpoint details
    endpoint = manager.get_endpoint_details(vpc_endpoint_id)
    if endpoint:
        print(f"  Endpoint ID: {vpc_endpoint_id}")
        print(f"  Owner: {endpoint.get('OwnerId', 'Unknown')}")
        print(f"  VPC: {endpoint.get('VpcId', 'Unknown')}")
        print()

    # Confirm
    confirm = input("Reject this request? [y/N]: ")
    if confirm.lower() != 'y':
        print("❌ Cancelled.")
        return

    # Reject
    success = manager.reject_connection(service_id, vpc_endpoint_id)

    if success:
        print("\n🚫 Connection rejected successfully!")
        print(f"\nNotify tenant that their request for {vpc_endpoint_id} was denied.")


def auto_approve_pending(manager: PrivateLinkManager, service_id: str, allowed_principals: List[str]):
    """Auto-approve pending requests from allowed principals"""
    print(f"\n🤖 Auto-approving pending requests from allowed principals...\n")

    requests = manager.list_connection_requests(
        service_id,
        state='PendingAcceptance'
    )

    if not requests:
        print("  No pending requests.")
        return

    approved_count = 0

    for req in requests:
        endpoint_id = req['VpcEndpointId']
        owner = req['VpcEndpointOwner']

        # Check if owner is in allowed principals
        owner_arn = f"arn:aws:iam::{owner}:root"

        if owner_arn in allowed_principals or "*" in allowed_principals:
            print(f"  ✅ Auto-approving {endpoint_id} (owner: {owner})")
            success = manager.approve_connection(service_id, endpoint_id)
            if success:
                approved_count += 1
        else:
            print(f"  ⏭️  Skipping {endpoint_id} (owner {owner} not in allowed list)")

    print(f"\n✅ Auto-approved {approved_count} connection(s).")


def main():
    parser = argparse.ArgumentParser(
        description="Manage PrivateLink connection requests for MRGC"
    )

    parser.add_argument(
        '--region',
        default='us-east-1',
        help='AWS region (default: us-east-1)'
    )

    parser.add_argument(
        '--service-id',
        required=True,
        help='VPC Endpoint Service ID (vpce-svc-xxx)'
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # List pending
    subparsers.add_parser('list-pending', help='List pending connection requests')

    # List all
    subparsers.add_parser('list-all', help='List all connections')

    # Approve
    approve_parser = subparsers.add_parser('approve', help='Approve a connection request')
    approve_parser.add_argument('--endpoint-id', required=True, help='VPC Endpoint ID to approve')

    # Reject
    reject_parser = subparsers.add_parser('reject', help='Reject a connection request')
    reject_parser.add_argument('--endpoint-id', required=True, help='VPC Endpoint ID to reject')

    # Auto-approve
    auto_parser = subparsers.add_parser('auto-approve', help='Auto-approve pending requests from allowed principals')
    auto_parser.add_argument(
        '--allowed-principals',
        nargs='+',
        required=True,
        help='List of allowed AWS account IDs (e.g., 111122223333 444455556666)'
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize manager
    manager = PrivateLinkManager(args.region)

    # Execute command
    if args.command == 'list-pending':
        list_pending_requests(manager, args.service_id)

    elif args.command == 'list-all':
        list_all_connections(manager, args.service_id)

    elif args.command == 'approve':
        approve_request(manager, args.service_id, args.endpoint_id)

    elif args.command == 'reject':
        reject_request(manager, args.service_id, args.endpoint_id)

    elif args.command == 'auto-approve':
        # Convert account IDs to ARNs
        allowed_principals = [
            f"arn:aws:iam::{account_id}:root"
            for account_id in args.allowed_principals
        ]
        auto_approve_pending(manager, args.service_id, allowed_principals)


if __name__ == '__main__':
    main()

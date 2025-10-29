# Transit Gateway Cross-Region Peering
# Note: This file should be used in a separate root module that manages cross-region peering

# This is a template - actual peering must be managed at the root level
# because it requires providers for multiple regions

# Example usage in root module:
#
# # Peering from us-east-1 to us-east-2
# resource "aws_ec2_transit_gateway_peering_attachment" "use1_to_use2" {
#   provider = aws.us-east-1
#
#   peer_region             = "us-east-2"
#   peer_transit_gateway_id = module.tgw_use2.transit_gateway_id
#   transit_gateway_id      = module.tgw_use1.transit_gateway_id
#
#   tags = {
#     Name = "mrgc-tgw-peering-use1-use2"
#     Side = "Requester"
#   }
# }
#
# # Accept peering in us-east-2
# resource "aws_ec2_transit_gateway_peering_attachment_accepter" "use2_from_use1" {
#   provider = aws.us-east-2
#
#   transit_gateway_attachment_id = aws_ec2_transit_gateway_peering_attachment.use1_to_use2.id
#
#   tags = {
#     Name = "mrgc-tgw-peering-use1-use2"
#     Side = "Accepter"
#   }
# }
#
# # Add routes in us-east-1 to reach us-east-2
# resource "aws_ec2_transit_gateway_route" "use1_to_use2" {
#   provider = aws.us-east-1
#
#   destination_cidr_block         = "10.66.64.0/18"  # us-east-2 CIDR
#   transit_gateway_attachment_id  = aws_ec2_transit_gateway_peering_attachment.use1_to_use2.id
#   transit_gateway_route_table_id = module.tgw_use1.transit_gateway_association_default_route_table_id
# }
#
# # Add routes in us-east-2 to reach us-east-1
# resource "aws_ec2_transit_gateway_route" "use2_to_use1" {
#   provider = aws.us-east-2
#
#   destination_cidr_block         = "10.66.0.0/18"   # us-east-1 CIDR
#   transit_gateway_attachment_id  = aws_ec2_transit_gateway_peering_attachment.use1_to_use2.id
#   transit_gateway_route_table_id = module.tgw_use2.transit_gateway_association_default_route_table_id
# }

# Variables needed for peering (add to variables.tf if implementing)
#
# variable "peer_region" {
#   description = "Peer region for Transit Gateway peering"
#   type        = string
#   default     = null
# }
#
# variable "peer_transit_gateway_id" {
#   description = "Peer Transit Gateway ID"
#   type        = string
#   default     = null
# }
#
# variable "peer_cidr_blocks" {
#   description = "List of CIDR blocks in peer region"
#   type        = list(string)
#   default     = []
# }

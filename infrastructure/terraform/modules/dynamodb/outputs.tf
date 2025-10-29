# DynamoDB Module Outputs

output "gpu_instances_table_name" {
  description = "GPU instances table name"
  value       = aws_dynamodb_table.gpu_instances.name
}

output "gpu_instances_table_arn" {
  description = "GPU instances table ARN"
  value       = aws_dynamodb_table.gpu_instances.arn
}

output "gpu_instances_stream_arn" {
  description = "GPU instances table stream ARN"
  value       = aws_dynamodb_table.gpu_instances.stream_arn
}

output "routing_state_table_name" {
  description = "Routing state table name"
  value       = aws_dynamodb_table.routing_state.name
}

output "routing_state_table_arn" {
  description = "Routing state table ARN"
  value       = aws_dynamodb_table.routing_state.arn
}

output "routing_state_stream_arn" {
  description = "Routing state table stream ARN"
  value       = aws_dynamodb_table.routing_state.stream_arn
}

output "autoscaling_state_table_name" {
  description = "Autoscaling state table name"
  value       = aws_dynamodb_table.autoscaling_state.name
}

output "autoscaling_state_table_arn" {
  description = "Autoscaling state table ARN"
  value       = aws_dynamodb_table.autoscaling_state.arn
}

output "autoscaling_state_stream_arn" {
  description = "Autoscaling state table stream ARN"
  value       = aws_dynamodb_table.autoscaling_state.stream_arn
}

output "cleanup_validation_table_name" {
  description = "Cleanup validation table name"
  value       = aws_dynamodb_table.cleanup_validation.name
}

output "cleanup_validation_table_arn" {
  description = "Cleanup validation table ARN"
  value       = aws_dynamodb_table.cleanup_validation.arn
}

output "cleanup_validation_stream_arn" {
  description = "Cleanup validation table stream ARN"
  value       = aws_dynamodb_table.cleanup_validation.stream_arn
}

output "metrics_table_name" {
  description = "Metrics table name"
  value       = aws_dynamodb_table.metrics.name
}

output "metrics_table_arn" {
  description = "Metrics table ARN"
  value       = aws_dynamodb_table.metrics.arn
}

output "metrics_stream_arn" {
  description = "Metrics table stream ARN"
  value       = aws_dynamodb_table.metrics.stream_arn
}

output "all_table_names" {
  description = "List of all table names"
  value = [
    aws_dynamodb_table.gpu_instances.name,
    aws_dynamodb_table.routing_state.name,
    aws_dynamodb_table.autoscaling_state.name,
    aws_dynamodb_table.cleanup_validation.name,
    aws_dynamodb_table.metrics.name
  ]
}

output "all_table_arns" {
  description = "List of all table ARNs"
  value = [
    aws_dynamodb_table.gpu_instances.arn,
    aws_dynamodb_table.routing_state.arn,
    aws_dynamodb_table.autoscaling_state.arn,
    aws_dynamodb_table.cleanup_validation.arn,
    aws_dynamodb_table.metrics.arn
  ]
}

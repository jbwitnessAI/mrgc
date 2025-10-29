# Global State Management

This application provides centralized state management for the Multi-Region GPU Cluster using DynamoDB Global Tables.

## Components

### 1. State Manager (`state_manager.py`)
Low-level interface to DynamoDB Global Tables. Provides CRUD operations for all state tables.

**Tables:**
- `gpu_instances` - GPU instance registry
- `routing_state` - Routing scores and health
- `autoscaling_state` - Capacity and scaling decisions
- `cleanup_validation` - Car Wash validation results
- `metrics` - Aggregated cluster metrics

### 2. Instance Registry (`instance_registry.py`)
High-level interface for managing GPU instance lifecycle.

**Key Operations:**
- Register new instances
- Mark instances available/draining/quarantined
- Send heartbeats
- Update routing metrics
- Get available instances by region/model pool

### 3. Metrics Collector (`metrics_collector.py`)
Collects and aggregates cluster metrics.

**Metrics:**
- Requests per second (RPS)
- Queue depth per instance
- Model load time
- Inference latency (P50, P95, P99)
- Nitro Enclave operation duration
- Cleanup validation results

## Usage

### Initialize State Manager

```python
from state_manager import StateManager

# Create state manager for current region
state_mgr = StateManager(region="us-east-1", table_prefix="mrgc")

# Register a new instance
state_mgr.register_instance(
    instance_id="i-1234567890abcdef0",
    region="us-east-1",
    model_pool="model-a",
    ip_address="10.66.10.50",
    subnet_id="subnet-12345",
    availability_zone="us-east-1a",
    metadata={"ami_id": "ami-12345"}
)

# Send heartbeat
state_mgr.heartbeat(instance_id="i-1234567890abcdef0", queue_depth=3)

# Update instance state
state_mgr.update_instance_state(
    instance_id="i-1234567890abcdef0",
    state="available",
    queue_depth=0
)
```

### Use Instance Registry

```python
from instance_registry import InstanceRegistry, HealthStatus

# Initialize registry
registry = InstanceRegistry(region="us-east-1")

# Register new instance (higher level)
registry.register_new_instance(
    instance_id="i-1234567890abcdef0",
    region="us-east-1",
    model_pool="model-a",
    ip_address="10.66.10.50",
    subnet_id="subnet-12345",
    availability_zone="us-east-1a",
    subnet_cidr="10.66.10.0/23"
)

# Mark instance ready for traffic
registry.mark_instance_available("i-1234567890abcdef0")

# Update routing metrics (automatic scoring)
registry.update_routing_metrics(
    instance_id="i-1234567890abcdef0",
    queue_depth=2,
    avg_latency_ms=150.0,
    health_status=HealthStatus.HEALTHY
)

# Get best instances for routing
best_instances = registry.get_best_instances_for_routing(
    region="us-east-1",
    limit=5
)

for inst in best_instances:
    print(f"{inst.instance_id}: score={inst.routing_score:.2f}, queue={inst.queue_depth}")
```

### Collect Metrics

```python
from metrics_collector import MetricsCollector

# Initialize collector
collector = MetricsCollector(region="us-east-1")

# Record RPS
collector.record_rps(
    region="us-east-1",
    model_pool="model-a",
    rps=45.2
)

# Record model load time
collector.record_model_load_time(
    region="us-east-1",
    model_pool="model-a",
    load_time_seconds=32.5
)

# Record inference latency
collector.record_inference_latency(
    region="us-east-1",
    model_pool="model-a",
    latency_ms=150.0,
    percentile="p95"
)

# Get cluster health summary
health = collector.get_cluster_health_summary()
print(f"Total RPS: {health['total_rps']:.2f}")
print(f"Total Instances: {health['total_instances']}")
print(f"Avg Queue Depth: {health['avg_queue_depth']:.2f}")
```

## DynamoDB Global Table Replication

All tables replicate across 3 regions:
- us-east-1 (primary)
- us-east-2 (replica)
- us-west-2 (replica)

**Replication Latency**: Typically < 1 second

Applications in any region can:
- Read from local replica (low latency)
- Write to any replica (propagates globally)
- Handle eventual consistency

## Routing Score Algorithm

The routing score (0-100, higher is better) is calculated as:

```
routing_score = (queue_score * 0.50) +
                (latency_score * 0.30) +
                (health_score * 0.20)

where:
  queue_score = max(0, 100 - (queue_depth * 10))
  latency_score = max(0, 100 - (avg_latency_ms / 10))
  health_score = 100 (healthy), 50 (degraded), 0 (unhealthy)
```

**Example:**
- Queue depth: 2 → queue_score = 80
- Avg latency: 150ms → latency_score = 85
- Health: healthy → health_score = 100
- **Routing score: 85.5**

## IAM Permissions

The application needs these DynamoDB permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:BatchGetItem",
        "dynamodb:BatchWriteItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:*:*:table/mrgc-*",
        "arn:aws:dynamodb:*:*:table/mrgc-*/index/*"
      ]
    }
  ]
}
```

## Error Handling

All methods return `bool` for success/failure or raise exceptions for critical errors.

**Retry Strategy:**
- Use exponential backoff for throttling errors
- Retry up to 3 times for transient failures
- Log all errors with context

**Example:**
```python
import time

def retry_with_backoff(func, *args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            if e.response['Error']['Code'] == 'ProvisionedThroughputExceededException':
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
            raise
```

## Monitoring

CloudWatch metrics are automatically published:
- `dynamodb.UserErrors` - Application errors
- `dynamodb.SystemErrors` - AWS service errors
- `dynamodb.ReplicationLatency` - Cross-region delay
- `dynamodb.ConsumedReadCapacityUnits` - Read throughput
- `dynamodb.ConsumedWriteCapacityUnits` - Write throughput

## Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Run unit tests
pytest tests/unit/test_state_manager.py
pytest tests/unit/test_instance_registry.py
pytest tests/unit/test_metrics_collector.py

# Run integration tests (requires AWS credentials)
pytest tests/integration/test_global_state.py
```

## Performance

**Read Latency**: 1-5ms (local region)
**Write Latency**: 5-15ms (local region)
**Replication Latency**: < 1 second (cross-region)

**Throughput**: On-demand pricing scales automatically

## Security

- All data encrypted at rest with KMS
- All data encrypted in transit with TLS 1.2+
- Access via VPC endpoints (no internet traversal)
- IAM-based access control
- CloudTrail audit logging

## Disaster Recovery

- Point-in-time recovery enabled (restore to any point in last 35 days)
- Global table replication for multi-region availability
- Automatic failover to nearest region
- No single point of failure

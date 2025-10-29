# DynamoDB Global Tables Module

This module creates DynamoDB Global Tables for managing state across all regions in the Multi-Region GPU Cluster.

## Tables

### 1. GPU Instances Table
**Purpose**: Track all GPU instances across all regions

**Schema**:
```
instance_id (PK)        - i-xxxxxxxxx
region                  - us-east-1, us-east-2, us-west-2
model_pool              - model-a, model-b, model-c
state                   - launching, available, draining, terminated, quarantined
queue_depth             - Number of active requests (0-10)
last_heartbeat          - Unix timestamp of last heartbeat
launch_time             - Unix timestamp when launched
ip_address              - Private IP address
subnet_id               - Subnet ID
availability_zone       - AZ name
metadata                - JSON blob with additional info
ttl                     - Auto-cleanup timestamp (7 days after termination)
```

**Indexes**:
- `region-index`: Query instances by region
- `model-pool-index`: Query instances by model pool
- `state-index`: Query instances by state (e.g., all "available" instances)

### 2. Routing State Table
**Purpose**: Store current routing scores and health status for intelligent routing

**Schema**:
```
instance_id (PK)        - i-xxxxxxxxx
region                  - us-east-1, us-east-2, us-west-2
routing_score           - Float 0-100 (higher is better)
queue_depth             - Current queue depth (0-10)
avg_latency_ms          - Average request latency in ms
health_status           - healthy, degraded, unhealthy
last_updated            - Unix timestamp
subnet_cidr             - Subnet CIDR for affinity routing
ttl                     - Auto-cleanup after 1 hour of no updates
```

**Indexes**:
- `region-score-index`: Find best instances by region sorted by score

### 3. Autoscaling State Table
**Purpose**: Track capacity and scaling decisions

**Schema**:
```
model_pool (PK)         - model-a, model-b, model-c
timestamp (SK)          - Unix timestamp
region                  - us-east-1, us-east-2, us-west-2
current_capacity        - Number of instances running
desired_capacity        - Target number of instances
min_capacity            - Minimum allowed instances
max_capacity            - Maximum allowed instances
current_rps             - Current requests per second
target_rps              - Target RPS per instance (1.0-1.5)
scaling_action          - scale-up, scale-down, none
reason                  - Reason for scaling decision
ttl                     - Auto-cleanup after 30 days
```

**Indexes**:
- `region-timestamp-index`: Query scaling history by region

### 4. Cleanup Validation Table (Car Wash)
**Purpose**: Track security cleanup validation before instance reuse

**Schema**:
```
instance_id (PK)        - i-xxxxxxxxx
validation_timestamp (SK) - Unix timestamp
validation_status       - pending, passed, failed
gpu_memory_wiped        - true/false (10x zero overwrite)
system_memory_wiped     - true/false
enclave_stopped         - true/false
integrity_check         - SHA256 hash of validation
failure_reason          - Error message if failed
quarantine_reason       - Reason for quarantine if failed
validator_id            - ID of validation process
ttl                     - Auto-cleanup after 90 days (compliance)
```

**Indexes**:
- `status-timestamp-index`: Find all failed validations

### 5. Metrics Table
**Purpose**: Store aggregated metrics for monitoring

**Schema**:
```
metric_name (PK)        - rps, queue_depth, model_load_time, etc.
timestamp (SK)          - Unix timestamp (minute granularity)
region                  - us-east-1, us-east-2, us-west-2
value                   - Metric value (float)
unit                    - Count, Seconds, Milliseconds, etc.
dimensions              - JSON blob with additional dimensions
ttl                     - Auto-cleanup after 30 days
```

**Indexes**:
- `region-timestamp-index`: Query metrics by region

## Global Table Configuration

All tables are configured as **DynamoDB Global Tables** with replicas in all 3 regions:
- us-east-1 (Primary)
- us-east-2 (Replica)
- us-west-2 (Replica)

**Replication Characteristics**:
- **Consistency**: Eventual consistency (typically < 1 second)
- **Conflict Resolution**: Last-writer-wins based on timestamp
- **Encryption**: Server-side encryption with KMS
- **Backup**: Point-in-time recovery enabled

## Usage

```hcl
module "dynamodb" {
  source = "../../modules/dynamodb"

  name_prefix = "mrgc-prod"

  replica_regions = [
    "us-east-2",
    "us-west-2"
  ]

  enable_point_in_time_recovery = true
  enable_cloudwatch_alarms      = true

  tags = {
    Project     = "MRGC"
    Environment = "production"
  }
}
```

## Access Patterns

### Regional Router: Find Best GPU Instance
```python
# Query routing_state table by region, sorted by score
response = dynamodb.query(
    TableName='mrgc-routing-state',
    IndexName='region-score-index',
    KeyConditionExpression='region = :region',
    ExpressionAttributeValues={':region': 'us-east-1'},
    ScanIndexForward=False,  # Descending order (highest score first)
    Limit=10
)
```

### Autoscaler: Check Current Capacity
```python
# Query autoscaling_state table for recent capacity
response = dynamodb.query(
    TableName='mrgc-autoscaling-state',
    KeyConditionExpression='model_pool = :pool AND timestamp > :time',
    ExpressionAttributeValues={
        ':pool': 'model-a',
        ':time': int(time.time()) - 300  # Last 5 minutes
    },
    ScanIndexForward=False,
    Limit=1
)
```

### GPU Instance: Register on Launch
```python
# Put instance into gpu_instances table
dynamodb.put_item(
    TableName='mrgc-gpu-instances',
    Item={
        'instance_id': 'i-1234567890abcdef0',
        'region': 'us-east-1',
        'model_pool': 'model-a',
        'state': 'launching',
        'queue_depth': 0,
        'last_heartbeat': int(time.time()),
        'launch_time': int(time.time()),
        'ttl': int(time.time()) + 604800  # 7 days
    }
)
```

### Car Wash: Validate Cleanup
```python
# Record cleanup validation
dynamodb.put_item(
    TableName='mrgc-cleanup-validation',
    Item={
        'instance_id': 'i-1234567890abcdef0',
        'validation_timestamp': int(time.time()),
        'validation_status': 'passed',
        'gpu_memory_wiped': True,
        'system_memory_wiped': True,
        'enclave_stopped': True,
        'integrity_check': 'sha256:abc123...',
        'ttl': int(time.time()) + 7776000  # 90 days
    }
)
```

## IAM Permissions

Applications need the following DynamoDB permissions:

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
        "dynamodb:Scan"
      ],
      "Resource": [
        "arn:aws:dynamodb:*:*:table/mrgc-*",
        "arn:aws:dynamodb:*:*:table/mrgc-*/index/*"
      ]
    }
  ]
}
```

## Cost

**Baseline (50 GPU instances, 75 RPS)**:
- On-demand pricing: ~$25-50/month
- Operations: ~10 million reads + 5 million writes per month

**Scale (150 GPU instances, 225 RPS)**:
- On-demand pricing: ~$75-150/month

*On-demand pricing is recommended due to variable load patterns*

## Monitoring

CloudWatch alarms are automatically created for:
1. **UserErrors**: Application errors (threshold: > 10 in 5 minutes)
2. **SystemErrors**: AWS service errors (threshold: > 0)
3. **ReplicationLatency**: Cross-region replication delay (threshold: > 2 seconds)

## Disaster Recovery

- **Point-in-time recovery**: Restore table to any point in last 35 days
- **Global table replication**: If one region fails, other regions continue operating
- **Automatic failover**: Applications automatically use nearest available replica

## Security

- **Encryption at rest**: KMS encryption for all data
- **Encryption in transit**: TLS 1.2+ for all API calls
- **VPC Endpoints**: Access via private VPC endpoints (no internet traversal)
- **IAM**: Fine-grained access control per table and operation
- **Audit logs**: All API calls logged to CloudTrail

## TTL (Time-to-Live)

All tables have TTL enabled for automatic cleanup:
- **gpu_instances**: 7 days after termination
- **routing_state**: 1 hour after last update
- **autoscaling_state**: 30 days
- **cleanup_validation**: 90 days (compliance requirement)
- **metrics**: 30 days

This prevents unbounded table growth and reduces costs.

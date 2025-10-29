# Regional Router

The Regional Router is responsible for intelligent request routing, health monitoring, and automatic failover in the Multi-Region GPU Cluster.

## Components

### 1. Health Monitor (`health_monitor.py`)
Continuously monitors health of GPU instances and regions.

**Functions:**
- Check instance health via HTTP endpoint
- Detect stale instances (no heartbeat)
- Calculate region-wide health metrics
- Update routing state based on health

**Health Checks:**
- HTTP GET to `http://{instance-ip}:8080/health` every 30 seconds
- Timeout: 10 seconds
- Failure threshold: 3 consecutive failures
- Metrics: Response time, queue depth, status code

### 2. Failover Handler (`failover_handler.py`)
Manages automatic cross-region failover.

**Functions:**
- Evaluate region health for failover decisions
- Initiate failover to healthy regions
- Manage recovery process
- Provide routing preferences based on state

**Failover States:**
- `NORMAL`: 80-100% instances healthy, normal routing
- `DEGRADED`: 50-80% healthy, reduce traffic 30%
- `FAILOVER_ACTIVE`: <30% healthy, redirect 95% traffic
- `RECOVERING`: 80%+ healthy, gradually return traffic

### 3. Router (`router.py`) - To be implemented
Main routing logic for incoming requests.

**Functions:**
- Receive requests from Global Accelerator / NLB
- Select best GPU instance based on routing score
- Forward request to selected instance
- Handle retries and circuit breaking

## Architecture

```
┌─────────────────────────────────────────────┐
│         Global Accelerator / NLB            │
└──────────────────┬──────────────────────────┘
                   │
                   ↓
┌──────────────────────────────────────────────┐
│          Regional Router (ECS Fargate)       │
│                                              │
│  ┌────────────────────────────────────┐    │
│  │   Request Handler                  │    │
│  │   - Receive request                │    │
│  │   - Select best instance           │    │
│  │   - Forward to GPU                 │    │
│  └────────────────────────────────────┘    │
│                                              │
│  ┌────────────────────────────────────┐    │
│  │   Health Monitor (Background)      │    │
│  │   - Check instance health (30s)    │    │
│  │   - Detect failures                │    │
│  │   - Update routing state           │    │
│  └────────────────────────────────────┘    │
│                                              │
│  ┌────────────────────────────────────┐    │
│  │   Failover Handler (Background)    │    │
│  │   - Monitor region health (60s)    │    │
│  │   - Initiate failover if needed    │    │
│  │   - Manage recovery                │    │
│  └────────────────────────────────────┘    │
└──────────────────┬───────────────────────────┘
                   │
                   ↓
        ┌──────────┴──────────┐
        │                     │
        ↓                     ↓
┌───────────────┐    ┌───────────────┐
│ GPU Instance  │    │ GPU Instance  │
│ us-east-1a    │    │ us-east-1b    │
└───────────────┘    └───────────────┘
```

## Usage

### Run Health Monitor

```python
from health_monitor import HealthMonitor
from applications.global_state.state_manager import StateManager

# Initialize
state_mgr = StateManager(region="us-east-1")
health_monitor = HealthMonitor(
    region="us-east-1",
    state_manager=state_mgr,
    health_check_interval=30,
    failure_threshold=3
)

# Run continuous health checks (blocking)
health_monitor.run_health_check_loop()
```

### Run Failover Handler

```python
from failover_handler import FailoverHandler
from health_monitor import HealthMonitor
from applications.global_state.state_manager import StateManager
from applications.global_state.metrics_collector import MetricsCollector

# Initialize
state_mgr = StateManager(region="us-east-1")
metrics_collector = MetricsCollector(region="us-east-1")
health_monitor = HealthMonitor(region="us-east-1", state_manager=state_mgr)

failover_handler = FailoverHandler(
    region="us-east-1",
    state_manager=state_mgr,
    metrics_collector=metrics_collector
)

# Run continuous failover monitoring (blocking)
failover_handler.run_failover_monitor_loop(
    health_monitor=health_monitor,
    check_interval=60
)
```

### Check Instance Health Manually

```python
from health_monitor import HealthMonitor

health_monitor = HealthMonitor(region="us-east-1", state_manager=state_mgr)

# Check single instance
health = health_monitor.check_instance_health(
    instance_id="i-1234567890abcdef0",
    ip_address="10.66.10.50"
)

print(f"Status: {health.status.value}")
print(f"Response time: {health.response_time_ms:.0f}ms")
print(f"Consecutive failures: {health.consecutive_failures}")

# Check all instances
all_health = health_monitor.check_all_instances()
for h in all_health:
    print(f"{h.instance_id}: {h.status.value}")

# Calculate region health
region_health = health_monitor.calculate_region_health(all_health)
print(f"Region: {region_health.status.value}")
print(f"Healthy: {region_health.healthy_instances}/{region_health.total_instances}")
```

### Simulate Failover

```python
from failover_handler import FailoverHandler

failover_handler = FailoverHandler(
    region="us-east-1",
    state_manager=state_mgr,
    metrics_collector=metrics_collector
)

# Simulate regional failure for testing
failover_handler.simulate_regional_failure("us-east-1")

# Check failover status
summary = failover_handler.get_failover_summary()
print(f"State: {summary['current_state']}")
print(f"Routing: {summary['routing_preference']}")
```

## Configuration

Configuration is loaded from `config/failover-policies.yaml`:

```yaml
health_check:
  interval_seconds: 30
  timeout_seconds: 10
  failure_threshold: 3

failover:
  degraded_threshold: 0.5   # 50%
  unhealthy_threshold: 0.3  # 30%
  recovery_threshold: 0.8   # 80%
```

## Health Check Endpoint

GPU instances must implement `/health` endpoint:

```python
# Example health endpoint on GPU instance
@app.route('/health')
def health():
    return {
        "status": "healthy",
        "queue_depth": 2,
        "avg_latency_ms": 150.0,
        "model_loaded": True,
        "enclave_running": True
    }, 200
```

## Routing Score Algorithm

Instances are scored for routing (0-100, higher is better):

```
routing_score = (queue_score * 0.50) +
                (latency_score * 0.30) +
                (health_score * 0.20)

where:
  queue_score = max(0, 100 - (queue_depth * 10))
  latency_score = max(0, 100 - (response_time_ms / 10))
  health_score = 100 (healthy), 50 (degraded), 0 (unhealthy)
```

**Example:**
- Queue depth: 2 → queue_score = 80
- Response time: 200ms → latency_score = 80
- Health: healthy → health_score = 100
- **Routing score: 84.0**

## Failover Scenarios

### Scenario 1: Single Instance Failure

```
1. Instance fails health check at T+0
2. Retry at T+30s, T+60s, T+90s (all fail)
3. Mark instance UNHEALTHY at T+90s
4. routing_score set to 0 (no traffic)
5. Instance begins draining
6. Auto-scaler launches replacement
```

### Scenario 2: Regional Failure

```
1. Multiple instances fail in region
2. Region health drops below 30%
3. Failover handler initiates failover
4. Traffic redirected to healthy regions
5. Auto-scaler increases capacity in target regions
6. Recovery begins when region health > 80%
```

See [docs/diagrams/failover-scenarios.md](../../docs/diagrams/failover-scenarios.md) for detailed scenarios.

## Monitoring

### CloudWatch Metrics

Published by Health Monitor and Failover Handler:

```python
# Instance health
cloudwatch.put_metric_data(
    Namespace='MRGC/HealthMonitor',
    MetricData=[{
        'MetricName': 'InstanceHealth',
        'Value': 1.0 if healthy else 0.0,
        'Dimensions': [
            {'Name': 'InstanceId', 'Value': instance_id},
            {'Name': 'Region', 'Value': region}
        ]
    }]
)

# Region health
cloudwatch.put_metric_data(
    Namespace='MRGC/Failover',
    MetricData=[{
        'MetricName': 'RegionHealthRatio',
        'Value': healthy_instances / total_instances,
        'Dimensions': [
            {'Name': 'Region', 'Value': region}
        ]
    }]
)
```

### Alerts

Configure CloudWatch Alarms:

```bash
# Alert when region health drops below 50%
aws cloudwatch put-metric-alarm \
  --alarm-name mrgc-region-degraded \
  --metric-name RegionHealthRatio \
  --namespace MRGC/Failover \
  --statistic Average \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 0.5 \
  --comparison-operator LessThanThreshold \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:alerts

# Alert when failover is active
aws cloudwatch put-metric-alarm \
  --alarm-name mrgc-failover-active \
  --metric-name FailoverActive \
  --namespace MRGC/Failover \
  --statistic Sum \
  --period 60 \
  --evaluation-periods 1 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:critical-alerts
```

## Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Run unit tests
pytest tests/unit/test_health_monitor.py
pytest tests/unit/test_failover_handler.py

# Run integration tests
pytest tests/integration/test_failover.py

# Simulate failover
python scripts/testing/simulate-failure.py --region us-east-1
```

## Deployment

Regional Router runs in ECS Fargate in each region:

```yaml
# ECS Task Definition
TaskDefinition:
  Family: mrgc-regional-router
  RequiresCompatibilities:
    - FARGATE
  Cpu: 1024
  Memory: 2048
  ContainerDefinitions:
    - Name: router
      Image: mrgc-router:latest
      Command: ["python", "router.py"]
    - Name: health-monitor
      Image: mrgc-router:latest
      Command: ["python", "health_monitor_daemon.py"]
    - Name: failover-handler
      Image: mrgc-router:latest
      Command: ["python", "failover_daemon.py"]
```

## IAM Permissions

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
        "dynamodb:Query"
      ],
      "Resource": "arn:aws:dynamodb:*:*:table/mrgc-*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstanceStatus",
        "ec2:DescribeInstances"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:PutMetricData"
      ],
      "Resource": "*"
    }
  ]
}
```

## Security

- Health checks use HTTP (not HTTPS) within VPC (private network)
- All DynamoDB access via VPC endpoints (no internet)
- IAM roles for ECS tasks (no static credentials)
- Security groups restrict traffic to known sources

## Performance

- **Health check latency**: 10-500ms per instance
- **Parallel checks**: 20 instances checked concurrently
- **Total check time**: ~1-2 seconds for 50 instances
- **Memory usage**: ~200MB per router instance
- **CPU usage**: <10% during normal operations

## High Availability

- Regional Router runs in ECS Fargate (auto-healing)
- Multiple router instances per region (minimum 2)
- Health monitor and failover handler run as separate processes
- If router fails, ECS launches replacement within 60 seconds

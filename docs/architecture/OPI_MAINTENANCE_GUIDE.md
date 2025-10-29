# OPI Maintenance Guide

> **Guide for Maintainers: Managing OPI Framework and Integrations**

This guide is designed for project maintainers who need to manage, review, and maintain OPI integrations in the Simplicity indexer.

---

## Table of Contents

- [Maintainer Responsibilities](#maintainer-responsibilities)
- [OPI Review Process](#opi-review-process)
- [Configuration Management](#configuration-management)
- [Monitoring & Debugging](#monitoring--debugging)
- [Deployment Procedures](#deployment-procedures)
- [Security Considerations](#security-considerations)
- [Performance Monitoring](#performance-monitoring)
- [Troubleshooting Guide](#troubleshooting-guide)

---

## Maintainer Responsibilities

### Core Duties

1. **Code Review**: Review all OPI submissions for quality, security, and compliance
2. **Integration Testing**: Ensure new OPIs don't break existing functionality
3. **Configuration Management**: Manage OPI enablement/disablement
4. **Performance Monitoring**: Track OPI performance impact
5. **Security Audits**: Regular security reviews of OPI implementations
6. **Documentation**: Maintain up-to-date OPI documentation

### Review Checklist

When reviewing OPI submissions, ensure:

- [ ] **Code Quality**: Follows project coding standards
- [ ] **Test Coverage**: Comprehensive test suite (>80% coverage)
- [ ] **Security**: No security vulnerabilities or data leaks
- [ ] **Performance**: No significant performance degradation
- [ ] **Documentation**: Complete and accurate documentation
- [ ] **Integration**: Properly integrates with existing systems
- [ ] **Error Handling**: Robust error handling and logging
- [ ] **State Management**: Correct state transition logic

---

## OPI Review Process

### 1. Initial Review

```bash
# Check code quality
make lint
make format-check

# Run security scan
make security-scan

# Run full test suite
make test
```

### 2. Integration Testing

```bash
# Test OPI-specific functionality
pipenv run pytest tests/unit/opi/ -v
pipenv run pytest tests/integration/test_opi_* -v

# Test with different configurations
ENABLED_OPIS="test_opi,your_opi" pipenv run pytest tests/
```

### 3. Performance Testing

```bash
# Run performance tests
pipenv run pytest tests/integration/test_performance.py -v

# Monitor resource usage
pipenv run python -m cProfile -o profile.prof src/main.py --continuous
```

### 4. Security Audit

```bash
# Run security checks
pipenv run bandit -r src/opi/
pipenv run safety check

# Check for dependency vulnerabilities
pipenv run pip-audit
```

---

## Configuration Management

### OPI Configuration

The main configuration file for OPIs is located at `src/config.py`:

```python
class Settings(BaseSettings):
    # OPI Framework Settings
    ENABLE_OPI: bool = True
    STOP_ON_OPI_ERROR: bool = False
    ENABLED_OPIS: List[str] = [
        "test_opi",  # Test OPI for development
        # Add production OPIs here
    ]
    
    # OPI-specific settings
    OPI_VALIDATION_TIMEOUT: int = 30  # seconds
    OPI_MAX_RETRIES: int = 3
    OPI_LOG_LEVEL: str = "INFO"
```

### Environment-Specific Configuration

#### Development Environment

```bash
# .env.development
ENABLE_OPI=true
ENABLED_OPIS=test_opi
OPI_LOG_LEVEL=DEBUG
STOP_ON_OPI_ERROR=true
```

#### Production Environment

```bash
# .env.production
ENABLE_OPI=true
ENABLED_OPIS=production_opi_1,production_opi_2
OPI_LOG_LEVEL=INFO
STOP_ON_OPI_ERROR=false
```

### Dynamic OPI Management

OPIs can be enabled/disabled without code changes:

```python
# Runtime OPI management
from src.opi.registry import OPIRegistry

registry = OPIRegistry()

# Disable an OPI
registry.disable_processor("problematic_opi")

# Enable an OPI
registry.enable_processor("new_opi")

# Get status of all OPIs
status = registry.get_processor_status()
```

---

## Monitoring & Debugging

### Logging Configuration

OPI-specific logging is configured in `src/utils/logging.py`:

```python
# OPI-specific loggers
OPI_LOGGERS = {
    "src.opi.registry": "INFO",
    "src.opi.operations": "DEBUG",
    "src.opi.contracts": "INFO",
}

def configure_opi_logging():
    """Configure logging for OPI components."""
    for logger_name, level in OPI_LOGGERS.items():
        logger = structlog.get_logger(logger_name)
        logger.setLevel(getattr(logging, level))
```

### Monitoring Metrics

Key metrics to monitor for OPI health:

```python
# OPI Performance Metrics
OPI_METRICS = {
    "opi_operations_processed": "counter",
    "opi_processing_time": "histogram",
    "opi_errors": "counter",
    "opi_state_transitions": "counter",
    "opi_validation_failures": "counter",
}

# Example monitoring implementation
class OPIMonitor:
    def __init__(self):
        self.metrics = {}
    
    def record_operation_processed(self, opi_name: str, operation_type: str):
        """Record that an operation was processed."""
        key = f"opi_operations_processed_{opi_name}_{operation_type}"
        self.metrics[key] = self.metrics.get(key, 0) + 1
    
    def record_processing_time(self, opi_name: str, duration: float):
        """Record processing time for an OPI."""
        key = f"opi_processing_time_{opi_name}"
        if key not in self.metrics:
            self.metrics[key] = []
        self.metrics[key].append(duration)
```

### Debug Commands

```bash
# Enable debug logging
export OPI_LOG_LEVEL=DEBUG

# Run with OPI debugging
pipenv run python src/main.py --debug --opi-debug

# Check OPI status
curl http://localhost:8080/v1/indexer/opi/status

# Get OPI metrics
curl http://localhost:8080/v1/indexer/opi/metrics
```

---

## Deployment Procedures

### Pre-Deployment Checklist

- [ ] All tests passing
- [ ] Security scan clean
- [ ] Performance benchmarks met
- [ ] Documentation updated
- [ ] Configuration reviewed
- [ ] Backup created

### Deployment Steps

#### 1. Staging Deployment

```bash
# Deploy to staging
git checkout staging
git merge feature/your-opi
docker-compose -f docker-compose.staging.yml up -d

# Run integration tests
make test-integration-staging

# Monitor for issues
docker-compose -f docker-compose.staging.yml logs -f
```

#### 2. Production Deployment

```bash
# Create release branch
git checkout main
git checkout -b release/your-opi-v1.0.0

# Update version numbers
# Update CHANGELOG.md
# Update documentation

# Deploy to production
docker-compose -f docker-compose.prod.yml up -d

# Verify deployment
curl http://localhost:8080/v1/indexer/brc20/health
curl http://localhost:8080/v1/indexer/opi/status
```

#### 3. Rollback Procedure

```bash
# If issues detected, rollback
docker-compose -f docker-compose.prod.yml down
git checkout previous-stable-commit
docker-compose -f docker-compose.prod.yml up -d

# Verify rollback
curl http://localhost:8080/v1/indexer/brc20/health
```

### Blue-Green Deployment

For zero-downtime deployments:

```bash
# Deploy to green environment
docker-compose -f docker-compose.green.yml up -d

# Run health checks
./scripts/health-check.sh green

# Switch traffic to green
./scripts/switch-traffic.sh green

# Monitor for issues
./scripts/monitor-deployment.sh

# If successful, decommission blue
docker-compose -f docker-compose.blue.yml down
```

---

## Security Considerations

### OPI Security Review

#### 1. Input Validation

Ensure all OPI processors validate inputs:

```python
def validate_operation_input(self, operation_data: dict) -> bool:
    """Validate operation input for security."""
    # Check for SQL injection attempts
    if any("'" in str(v) for v in operation_data.values()):
        return False
    
    # Check for XSS attempts
    if any("<script>" in str(v).lower() for v in operation_data.values()):
        return False
    
    # Check for path traversal
    if any(".." in str(v) for v in operation_data.values()):
        return False
    
    return True
```

#### 2. State Validation

```python
def validate_state_transition(self, current_state: dict, new_command: StateUpdateCommand) -> bool:
    """Validate state transition for security."""
    # Prevent negative balances
    if hasattr(new_command, 'amount') and new_command.amount < 0:
        return False
    
    # Prevent unauthorized state changes
    if not self._is_authorized_transition(current_state, new_command):
        return False
    
    return True
```

#### 3. Access Control

```python
def check_operation_permissions(self, operation_data: dict, context: Context) -> bool:
    """Check if operation is authorized."""
    # Implement your authorization logic
    return True
```

### Security Monitoring

```python
# Security event logging
class OPISecurityMonitor:
    def __init__(self):
        self.security_logger = structlog.get_logger("opi.security")
    
    def log_security_event(self, event_type: str, details: dict):
        """Log security-related events."""
        self.security_logger.warning(
            "Security event detected",
            event_type=event_type,
            details=details,
            timestamp=datetime.utcnow().isoformat()
        )
```

---

## Performance Monitoring

### Key Performance Indicators (KPIs)

1. **Processing Time**: Average time to process OPI operations
2. **Throughput**: Operations processed per second
3. **Error Rate**: Percentage of failed operations
4. **Memory Usage**: Memory consumption by OPI processors
5. **Database Load**: Database queries generated by OPIs

### Performance Monitoring Setup

```python
# Performance monitoring configuration
PERFORMANCE_THRESHOLDS = {
    "max_processing_time": 1.0,  # seconds
    "max_memory_usage": 100,     # MB
    "max_error_rate": 0.01,      # 1%
    "max_db_queries_per_operation": 10,
}

class OPIPerformanceMonitor:
    def __init__(self):
        self.thresholds = PERFORMANCE_THRESHOLDS
        self.metrics = {}
    
    def check_performance(self, opi_name: str, metrics: dict) -> bool:
        """Check if OPI performance is within acceptable limits."""
        for metric, threshold in self.thresholds.items():
            if metrics.get(metric, 0) > threshold:
                self.logger.warning(
                    f"Performance threshold exceeded for {opi_name}",
                    metric=metric,
                    value=metrics[metric],
                    threshold=threshold
                )
                return False
        return True
```

### Performance Optimization

#### 1. Caching

```python
# Implement caching for frequently accessed data
from functools import lru_cache

class OptimizedOPIProcessor(BaseProcessor):
    @lru_cache(maxsize=1000)
    def _get_cached_balance(self, address: str, ticker: str) -> Decimal:
        """Cache balance lookups."""
        return self.validator.get_balance(address, ticker)
```

#### 2. Batch Processing

```python
def process_batch_operations(self, operations: List[dict], context: Context) -> List[ProcessingResult]:
    """Process multiple operations in batch for better performance."""
    results = []
    
    # Group operations by type for batch processing
    grouped_ops = self._group_operations_by_type(operations)
    
    for op_type, ops in grouped_ops.items():
        batch_result = self._process_batch(ops, context)
        results.extend(batch_result)
    
    return results
```

---

## Troubleshooting Guide

### Common Issues and Solutions

#### 1. OPI Not Processing Operations

**Symptoms**:
- Operations are not being routed to OPI processors
- No OPI-related logs appearing

**Diagnosis**:
```bash
# Check OPI configuration
curl http://localhost:8080/v1/indexer/opi/config

# Check OPI status
curl http://localhost:8080/v1/indexer/opi/status

# Check logs
docker-compose logs -f | grep -i opi
```

**Solutions**:
- Verify OPI is in `ENABLED_OPIS` list
- Check operation types are in `supported_operations`
- Ensure parser recognizes operation types
- Restart indexer service

#### 2. State Inconsistencies

**Symptoms**:
- Database state doesn't match expected state
- Balance calculations are incorrect

**Diagnosis**:
```bash
# Check state consistency
pipenv run python scripts/check_state_consistency.py

# Compare intermediate state with database
pipenv run python scripts/compare_states.py
```

**Solutions**:
- Review state transition logic
- Check for race conditions
- Verify atomic commit behavior
- Run state repair scripts

#### 3. Performance Degradation

**Symptoms**:
- Slow operation processing
- High memory usage
- Database timeouts

**Diagnosis**:
```bash
# Profile performance
pipenv run python -m cProfile -o profile.prof src/main.py

# Monitor resource usage
htop
iostat -x 1

# Check database performance
psql -c "SELECT * FROM pg_stat_activity WHERE state = 'active';"
```

**Solutions**:
- Optimize database queries
- Implement caching
- Add connection pooling
- Scale horizontally

#### 4. Memory Leaks

**Symptoms**:
- Memory usage continuously increases
- System becomes unresponsive

**Diagnosis**:
```bash
# Monitor memory usage
pipenv run python -m memory_profiler src/main.py

# Check for circular references
pipenv run python scripts/check_memory_leaks.py
```

**Solutions**:
- Review object lifecycle management
- Clear intermediate state regularly
- Use weak references where appropriate
- Implement garbage collection

### Emergency Procedures

#### 1. Disable Problematic OPI

```bash
# Disable OPI via configuration
export ENABLED_OPIS="test_opi"  # Remove problematic OPI

# Restart service
docker-compose restart indexer

# Verify OPI is disabled
curl http://localhost:8080/v1/indexer/opi/status
```

#### 2. Rollback to Previous Version

```bash
# Stop current service
docker-compose down

# Checkout previous version
git checkout previous-stable-tag

# Rebuild and restart
docker-compose up -d --build

# Verify rollback
curl http://localhost:8080/v1/indexer/brc20/health
```

#### 3. Database Recovery

```bash
# Stop indexer
docker-compose stop indexer

# Restore from backup
pg_restore -d simplicity_db backup_$(date -d yesterday +%Y%m%d).sql

# Restart indexer
docker-compose start indexer
```

---

## Maintenance Schedule

### Daily Tasks

- [ ] Check system health metrics
- [ ] Review error logs
- [ ] Monitor performance indicators
- [ ] Verify backup completion

### Weekly Tasks

- [ ] Review OPI performance reports
- [ ] Update security patches
- [ ] Clean up old logs
- [ ] Test disaster recovery procedures

### Monthly Tasks

- [ ] Full security audit
- [ ] Performance optimization review
- [ ] Documentation updates
- [ ] Capacity planning review

### Quarterly Tasks

- [ ] Complete system health check
- [ ] Disaster recovery testing
- [ ] Security penetration testing
- [ ] Architecture review

---

## Conclusion

Maintaining the OPI framework requires careful attention to security, performance, and reliability. By following this guide and implementing proper monitoring and procedures, maintainers can ensure the OPI system remains stable and secure.

For additional support or questions, please refer to the main project documentation or contact the development team.

---

**Happy Maintaining! 🔧**

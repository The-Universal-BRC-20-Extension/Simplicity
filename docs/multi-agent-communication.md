# Multi-Agent API Communication System

## Overview

This document describes the multi-agent API communication system that enables two Cursor agents to communicate effectively, where each agent is informed about its folder structure and architecture, and one agent can integrate APIs from the other agent's folder.

## Architecture

### System Components

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Agent A       │    │   Agent B       │    │   Shared        │
│   (API Provider)│◄──►│   (API Consumer)│    │   Infrastructure │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI       │    │   Integration   │    │   Configuration │
│   REST API      │    │   Layer         │    │   Management    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Key Features

1. **Service Discovery**: Dynamic agent registration and health monitoring
2. **Circuit Breaker Pattern**: Prevents cascade failures
3. **Retry Mechanisms**: Automatic retry with exponential backoff
4. **Health Checks**: Comprehensive health monitoring
5. **Structured Logging**: Detailed request/response logging
6. **Error Handling**: Standardized error responses
7. **Configuration Management**: Centralized configuration

## API Endpoints

### Agent Communication Endpoints

#### Register Agent
```http
POST /v1/agent/register
Content-Type: application/json

{
  "agent_id": "brc20_indexer",
  "name": "BRC-20 Indexer Agent",
  "base_url": "http://localhost:8080",
  "endpoints": ["/v1/indexer/brc20/health", "/v1/indexer/brc20/list"],
  "health_check_path": "/health",
  "timeout": 30,
  "retry_attempts": 3,
  "circuit_breaker_threshold": 5
}
```

#### Discover Agents
```http
GET /v1/agent/discover
```

Response:
```json
{
  "agents": [
    {
      "status": "healthy",
      "timestamp": "2024-01-01T00:00:00Z",
      "agent_id": "brc20_indexer",
      "services": {
        "database": "healthy",
        "redis": "healthy"
      },
      "response_time": 0.045
    }
  ],
  "total_agents": 1,
  "healthy_agents": 1,
  "timestamp": "2024-01-01T00:00:00Z"
}
```

#### Check Agent Health
```http
GET /v1/agent/health/{agent_id}
```

#### Make Cross-Agent Request
```http
POST /v1/agent/request
Content-Type: application/json

{
  "target_agent_id": "brc20_indexer",
  "endpoint": "/v1/indexer/brc20/list",
  "method": "GET",
  "data": {},
  "headers": {}
}
```

### Integration Endpoints

#### Get BRC-20 Tokens via Agent
```http
GET /v1/agent/integration/brc20/tokens?target_agent_id=brc20_indexer&limit=100
```

#### Get Token Info via Agent
```http
GET /v1/agent/integration/brc20/{ticker}/info?target_agent_id=brc20_indexer
```

#### Get OPI Operations via Agent
```http
GET /v1/agent/integration/opi/operations/{txid}?target_agent_id=brc20_indexer
```

## Usage Examples

### Python Client Example

```python
import asyncio
import aiohttp
from src.api.agent_communication import AgentConfig, agent_comm_service

async def main():
    # Register an agent
    config = AgentConfig(
        agent_id="brc20_indexer",
        name="BRC-20 Indexer Agent",
        base_url="http://localhost:8080",
        endpoints=["/v1/indexer/brc20/health", "/v1/indexer/brc20/list"]
    )
    
    agent_comm_service.register_agent(config)
    
    # Check agent health
    health = await agent_comm_service.check_agent_health("brc20_indexer")
    print(f"Agent health: {health.status}")
    
    # Make a request to the agent
    response = await agent_comm_service.make_request(
        "brc20_indexer",
        "/v1/indexer/brc20/list?limit=10"
    )
    print(f"Response: {response}")

# Run the example
asyncio.run(main())
```

### Using Integration Examples

```python
from src.api.agent_communication import AgentIntegrationExample

async def get_token_data():
    # Create integration instance
    integration = AgentIntegrationExample("brc20_indexer")
    
    # Get BRC-20 tokens
    tokens = await integration.get_brc20_tokens(limit=50)
    print(f"Found {len(tokens)} tokens")
    
    # Get specific token info
    token_info = await integration.get_token_info("ordi")
    print(f"Token info: {token_info}")
    
    # Get OPI operations
    operations = await integration.get_opi_operations("txid123...")
    print(f"Found {len(operations)} operations")
```

## Configuration

### Agent Configuration File

The system uses a YAML configuration file (`config/agent_communication.yaml`) to define:

- Default agent settings
- Communication parameters
- Security settings
- Monitoring configuration
- Integration endpoints

### Environment Variables

```bash
# Agent communication settings
AGENT_COMM_TIMEOUT=30
AGENT_COMM_RETRY_ATTEMPTS=3
AGENT_COMM_CIRCUIT_BREAKER_THRESHOLD=5

# Logging
AGENT_COMM_LOG_LEVEL=INFO
AGENT_COMM_LOG_FORMAT=json

# Monitoring
AGENT_COMM_METRICS_ENABLED=true
AGENT_COMM_METRICS_PREFIX=agent_communication
```

## Error Handling

### Standard Error Response Format

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request parameters",
    "details": {
      "field": "agent_id",
      "issue": "Required field missing"
    },
    "timestamp": "2024-01-01T00:00:00Z",
    "agent_id": "brc20_indexer"
  }
}
```

### Error Codes

- `VALIDATION_ERROR` (400): Invalid request parameters
- `UNAUTHORIZED` (401): Authentication required
- `FORBIDDEN` (403): Access denied
- `NOT_FOUND` (404): Resource not found
- `RATE_LIMIT_EXCEEDED` (429): Too many requests
- `INTERNAL_ERROR` (500): Internal server error
- `SERVICE_UNAVAILABLE` (503): Service temporarily unavailable

## Circuit Breaker Pattern

The system implements a circuit breaker pattern to prevent cascade failures:

### States

1. **Closed**: Normal operation, requests pass through
2. **Open**: Circuit is open, requests fail fast
3. **Half-Open**: Testing if service has recovered

### Configuration

```yaml
circuit_breaker:
  failure_threshold: 5
  recovery_timeout: 60
  expected_exception: "HTTPException"
```

## Health Checks

### Health Check Endpoint

```http
GET /v1/indexer/brc20/health
```

Response:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00Z",
  "services": {
    "database": "healthy",
    "redis": "healthy",
    "bitcoin_rpc": "healthy"
  }
}
```

### Health Check Configuration

```yaml
health_check:
  interval: 60
  timeout: 10
  failure_threshold: 3
```

## Monitoring and Observability

### Metrics Collected

- Request/response times
- Error rates
- Circuit breaker state changes
- Health check results
- Agent availability

### Logging

Structured logging with correlation IDs:

```python
logger.info(
    "API request processed",
    endpoint="/v1/indexer/brc20/list",
    response_time=0.045,
    status_code=200,
    agent_id="agent_b"
)
```

## Security Considerations

### Authentication

The system supports multiple authentication methods:

- Bearer tokens
- API keys
- OAuth2

### Rate Limiting

Configurable rate limiting per agent:

```yaml
rate_limit:
  enabled: true
  requests_per_minute: 100
```

### SSL/TLS

SSL verification can be configured:

```yaml
ssl_verify: true
ssl_cert_path: "/path/to/cert.pem"
```

## Development and Testing

### Development Mode

```yaml
development:
  debug: true
  mock_responses: false
  log_all_requests: true
  simulate_delay: false
```

### Testing

```python
import pytest
from src.api.agent_communication import AgentCommunicationService

@pytest.fixture
async def agent_service():
    async with AgentCommunicationService() as service:
        yield service

async def test_agent_registration(agent_service):
    config = AgentConfig(
        agent_id="test_agent",
        name="Test Agent",
        base_url="http://localhost:8080"
    )
    
    agent_service.register_agent(config)
    assert "test_agent" in agent_service.agents
```

## Deployment

### Docker Deployment

```dockerfile
# Add agent communication dependencies
RUN pip install aiohttp pydantic pyyaml

# Copy configuration
COPY config/agent_communication.yaml /app/config/

# Expose agent communication endpoints
EXPOSE 8080
```

### Environment Setup

```bash
# Start the API server
docker-compose up -d

# Register agents
curl -X POST http://localhost:8080/v1/agent/register \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "brc20_indexer",
    "name": "BRC-20 Indexer Agent",
    "base_url": "http://localhost:8080"
  }'

# Check agent health
curl http://localhost:8080/v1/agent/health/brc20_indexer
```

## Troubleshooting

### Common Issues

1. **Agent not found**: Ensure agent is registered before making requests
2. **Circuit breaker open**: Check target agent health and wait for recovery
3. **Timeout errors**: Increase timeout configuration or check network connectivity
4. **Authentication errors**: Verify API keys and authentication settings

### Debug Mode

Enable debug logging:

```python
import logging
logging.getLogger("src.api.agent_communication").setLevel(logging.DEBUG)
```

## Future Enhancements

1. **WebSocket Support**: Real-time communication between agents
2. **Message Queuing**: Asynchronous message processing
3. **Load Balancing**: Distribute requests across multiple agent instances
4. **Advanced Monitoring**: Prometheus metrics and Grafana dashboards
5. **Service Mesh Integration**: Istio/Linkerd integration for advanced networking

## Conclusion

This multi-agent communication system provides a robust, scalable solution for enabling two Cursor agents to communicate effectively. It includes comprehensive error handling, monitoring, and security features while maintaining simplicity and ease of use. 
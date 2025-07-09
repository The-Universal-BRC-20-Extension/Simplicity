# Simplicity

[![CI/CD Pipeline](https://github.com/The-Universal-BRC-20-Extension/simplicity-dev/actions/workflows/ci.yml/badge.svg)](https://github.com/The-Universal-BRC-20-Extension/simplicity-dev/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-379%20passing-brightgreen)](https://github.com/The-Universal-BRC20-Extension/simplicity-dev)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)

> **The best protocol is the one we build together - block by block**

An institutional-grade, production-ready indexer for Universal BRC-20 Extension token processing.

---

## 🚀 **Key Features**
- **High Performance**: Sub-20ms response times
- **Well Tested**: 379+ comprehensive tests with 100% pass rate
- **Real-time Processing**: Continuous blockchain synchronization
- **Production Ready**: Already 61+ BRC-20 tokens indexed in production
- **Docker Ready**: One-command deployment with Docker Compose
- **API Compatible**: Standard REST API with OpenAPI/Swagger documentation

---

## 🚀 Quick Start

> **You must have a fully synced Bitcoin Core node with `txindex=1` enabled.**
> See [Deployment Guide](docs/deployment/README.md) for full setup instructions.

### Docker Compose (Recommended)
```bash
cp .env.example .env
# Edit .env for your Bitcoin Core credentials and secrets
# Uncomment Docker DATABASE_URL and REDIS_URL, comment out localhost versions
# Change all default passwords and secrets if deploying beyond localhost

docker-compose up -d
curl http://localhost:8080/v1/indexer/brc20/health
# Expected output: { "status": "ok" }
```

### Manual/Hybrid
```bash
cp .env.example .env
# Edit .env for your environment (see docs/deployment/README.md)
pip install pipenv
pipenv install --dev
pipenv run alembic upgrade head
pipenv run python run.py --continuous
```

> **Security Warning:**
> If you expose any service to the internet, you MUST change all default passwords and users in your `.env` and `docker-compose.yml`. Never expose PostgreSQL or Redis directly to the internet.

---

## 📚 **API Documentation**

For complete API details, see the [Full API Documentation](./docs/api/README.md).

### Core Endpoints

```bash
# List all tokens
curl http://localhost:8080/v1/indexer/brc20/list

# Get token information
curl http://localhost:8080/v1/indexer/brc20/{tick}

# Get address balances
curl http://localhost:8080/v1/indexer/brc20/{tick}/holders/{address}

# Health check
curl http://localhost:8080/v1/indexer/brc20/health
```

**📖 Interactive API Documentation**: Available at `http://localhost:8080/docs`

---

## 🏗️ **Architecture**

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Bitcoin RPC   │───▶│  Simplicity     │───▶│   PostgreSQL    │
│   (Blockchain)  │    │   (Indexer)     │    │   (Database)    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                                ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Redis Cache   │◀───│   FastAPI       │───▶│   Monitoring    │
│   (Cache)       │    │   (API Server)  │    │   (Health)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

---

## 🧪 **Testing**

```bash
# Run all tests
pipenv run pytest

# Run with coverage
pipenv run pytest --cov=src --cov-report=html

# Run performance tests
pipenv run pytest tests/test_performance.py -v

# Run integration tests
pipenv run pytest tests/test_integration.py -v
```

---

## 📚 Documentation
- [Deployment Guide](docs/deployment/README.md) — Full setup, configuration, and troubleshooting
- [API Reference](docs/api/README.md) — Endpoints, schemas, and curl examples
- [Architecture](docs/architecture/README.md) — System overview and repo structure

---

## 🔄 **Deployment**

### Docker Deployment
```bash
# Build image
docker build -t universal-brc20-indexer .

# Run with compose
docker-compose up -d

# Scale services
docker-compose up -d --scale indexer=3
```

### Production Considerations
- **Database**: PostgreSQL with proper indexing
- **Cache**: Redis for performance optimization
- **Security**: Input validation and error handling
- **Scaling**: Horizontal scaling support

---

## 📄 **License**

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🤝 **Contributing**

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

---

## 📞 **Support**

- **Documentation**: [Full Documentation](docs/)
- **API Reference**: [Interactive API Docs](http://localhost:8080/docs)
- **Issues**: [GitHub Issues](https://github.com/The-Universal-BRC-20-Extension/simplicity-dev/issues)
- **Security**: [Security Policy](SECURITY.md)

--- 

# Contributing to Simplicity Indexer

Thank you for your interest in contributing! This guide provides clear processes for maintainers and contributors.

## 🚀 **Quick Start**

### Prerequisites
- Python 3.11+
- PostgreSQL 13+
- Redis 6+
- Docker (optional but recommended)

### Development Setup

```bash
# 1. Fork and clone
git clone https://github.com/The-Universal-BRC20-Extension/simplicity-dev.git
cd simplicity-dev

# 2. Install dependencies
pip install pipenv
pipenv install --dev

# 3. Setup environment
cp .env.example .env
# Edit .env with your configuration

# 4. Setup pre-commit hooks
pipenv run pre-commit install

# 5. Run tests to verify setup
pipenv run pytest

# 6. Start development with Docker
docker-compose up -d
```

### Development Setup (without pipenv)

If you don't want to use pipenv, you can use the generated requirements.txt:

```bash
# 1. Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Setup environment
cp .env.example .env
# Edit .env with your configuration

# 4. Run database migrations
alembic upgrade head

# 5. Run tests
pytest

# 6. Start development server
python run.py --continuous
```

## 🔄 **Development Workflow**

### Branch Strategy
```
main          # Production-ready code (protected)
├── develop   # Integration branch (protected)
├── feature/* # New features
├── bugfix/*  # Bug fixes
├── hotfix/*  # Critical production fixes
└── release/* # Release preparation
```

### Feature Development Process

1. **Create Feature Branch**
   ```bash
   git checkout develop
   git pull origin develop
   git checkout -b feature/your-feature-name
   ```

2. **Development Guidelines**
   - Follow existing code patterns
   - Add/update tests for new functionality
   - Ensure sub-20ms performance requirements
   - Update documentation if needed

3. **Code Quality Checks**
   ```bash
   # Run before committing
   pipenv run black src tests
   pipenv run flake8 src tests
   pipenv run mypy src
   pipenv run pytest
   ```

4. **Commit Standards**
   ```bash
   # Use conventional commits
   git commit -m "feat: add ticker search functionality"
   git commit -m "fix: resolve duplicate transaction processing"
   git commit -m "docs: update API documentation"
   ```

5. **Push and Create PR**
   ```bash
   git push origin feature/your-feature-name
   # Create PR via GitHub UI
   ```

## 🧪 **Testing Requirements**

### Test Categories
- **Unit Tests**: Test individual functions/classes
- **Integration Tests**: Test API endpoints and database interactions
- **Performance Tests**: Ensure sub-20ms response times
- **Security Tests**: Validate input sanitization

### Running Tests
```bash
# All tests
pipenv run pytest

# Specific categories
pipenv run pytest tests/test_api_endpoints.py
pipenv run pytest tests/test_performance.py
pipenv run pytest tests/test_integration.py

# With coverage
pipenv run pytest --cov=src --cov-report=html
```

### Test Requirements for PRs
- [ ] All existing tests pass
- [ ] New functionality has comprehensive tests
- [ ] Performance tests validate sub-20ms requirements
- [ ] Test coverage maintained above 80%

## 📋 **Pull Request Process**

### PR Requirements
1. **Branch**: Created from `develop`
2. **Tests**: All tests passing
3. **Performance**: Sub-20ms response times maintained
4. **Documentation**: Updated if needed
5. **Review**: At least 2 maintainer approvals

### PR Template Checklist
- [ ] Code follows project style guidelines
- [ ] Tests added for new functionality
- [ ] Performance requirements met
- [ ] Documentation updated
- [ ] No breaking changes (or documented)
- [ ] CI/CD pipeline passes

### Review Process
1. **Automated Checks**: CI/CD pipeline runs
2. **Code Review**: 2 maintainers review code
3. **Performance Review**: Validate performance metrics
4. **Documentation Review**: Ensure docs are updated
5. **Final Approval**: Maintainer approves and merges

## 🔧 **Code Standards**

### Python Style Guide
- **Formatting**: Black (line length 88)
- **Linting**: Flake8 with project configuration
- **Type Hints**: Required for all functions
- **Imports**: Sorted with isort
- **Security**: Bandit scanning

### Code Organization
```python
# Import order
import sys
from typing import Optional

import requests
from sqlalchemy import Column, Integer, String

from src.models.base import Base
from src.services.parser import BRC20Parser
```

### Performance Requirements
- **API Response Time**: <20ms average
- **Database Queries**: <20ms average
- **Memory Usage**: <512MB baseline
- **CPU Usage**: <50% under normal load

## 🚨 **Issue Management**

### Issue Types
- **Bug Report**: Use bug report template
- **Feature Request**: Use feature request template
- **Performance Issue**: Use performance issue template
- **Documentation**: Use documentation template

### Issue Labels
- `bug`: Bug reports
- `enhancement`: Feature requests
- `performance`: Performance issues
- `documentation`: Documentation updates
- `good first issue`: Beginner-friendly issues
- `help wanted`: Community contributions welcome

### Issue Triage Process
1. **Initial Review**: Maintainer reviews within 24 hours
2. **Label Assignment**: Appropriate labels assigned
3. **Priority Assignment**: Priority level determined
4. **Assignment**: Issue assigned to maintainer/contributor
5. **Status Updates**: Regular progress updates

## 🛡️ **Security Guidelines**

### Security Best Practices
- **Input Validation**: Validate all external inputs
- **SQL Injection**: Use SQLAlchemy ORM, no raw SQL
- **Error Handling**: Don't expose internal details
- **Logging**: Log security events appropriately

### Security Testing
```bash
# Run security checks
pipenv run bandit -r src
pipenv run safety check
```

### Vulnerability Reporting
- **Security Issues**: Report via blacknodebtc@protonmail.com
- **Response Time**: 24 hours acknowledgment
- **Disclosure**: Coordinated disclosure process

## 📊 **Performance Testing**

### Performance Benchmarks
```bash
# Run performance tests
pipenv run pytest tests/test_performance.py -v

# Load testing (if available)
pipenv run locust -f tests/load_test.py
```

### Performance Requirements
- **API Endpoints**: <20ms response time
- **Database Operations**: <20ms query time
- **Memory Usage**: <512MB baseline
- **Concurrent Users**: 100+ simultaneous

## 🔍 **Code Review Guidelines**

### What to Review
- **Functionality**: Does it work as expected?
- **Performance**: Does it meet performance requirements?
- **Security**: Are there security concerns?
- **Testing**: Are tests comprehensive?
- **Documentation**: Is documentation updated?

### Review Checklist
- [ ] Code follows project patterns
- [ ] Tests are comprehensive
- [ ] Performance requirements met
- [ ] Security considerations addressed
- [ ] Documentation updated
- [ ] No breaking changes

## 📚 **Documentation Requirements**

### Documentation Updates
- **API Changes**: Update OpenAPI/Swagger specs
- **New Features**: Add to README and docs/
- **Configuration**: Update .env.example
- **Deployment**: Update Docker/deployment guides

### Documentation Style
- **Clear and Concise**: Easy to understand
- **Examples**: Provide code examples
- **Up-to-Date**: Keep documentation current
- **Structured**: Follow existing patterns

## 🎯 **Release Process**

### Release Types
- **Major**: Breaking changes (v2.0.0)
- **Minor**: New features (v1.1.0)
- **Patch**: Bug fixes (v1.0.1)

### Release Workflow
1. **Feature Freeze**: No new features
2. **Testing**: Comprehensive testing
3. **Documentation**: Update documentation
4. **Release Branch**: Create release branch
5. **Final Testing**: Performance and security testing
6. **Tag Release**: Create git tag
7. **Deploy**: Deploy to production
8. **Announcement**: Announce release

## 📞 **Getting Help**

### Support Channels
- **GitHub Issues**: Technical questions
- **Documentation**: Comprehensive guides
- **Code Review**: PR feedback
- **Community**: [The Blacknode Community](./t.me/theblacknode)

### Maintainer Contacts
- **Technical Issues**: GitHub Issues
- **Security Issues**: blacknodebtc@protonmail.com
- **General Questions**: GitHub Discussions

---

**Thank you for contributing to Simplicity Indexer! 🚀** 

# Makefile for Simplicity BRC-20 Indexer
# Test execution and development utilities

.PHONY: help test test-unit test-integration test-functional test-all test-fast test-slow test-coverage clean install

# Default target
help:
	@echo "Available commands:"
	@echo "  make test          - Run all tests"
	@echo "  make test-unit     - Run unit tests only (fast)"
	@echo "  make test-integration - Run integration tests"
	@echo "  make test-functional - Run functional tests"
	@echo "  make test-fast     - Run unit + integration tests (fast)"
	@echo "  make test-slow     - Run functional tests (slow)"
	@echo "  make test-coverage - Run all tests with coverage report"
	@echo "  make clean         - Clean up temporary files"
	@echo "  make install       - Install dependencies"

# Run all tests
test:
	pipenv run pytest tests/ -v

# Run unit tests only (fastest)
test-unit:
	pipenv run pytest tests/unit/ -v

# Run integration tests
test-integration:
	pipenv run pytest tests/integration/ -v

# Run functional tests (slowest)
test-functional:
	pipenv run pytest tests/functional/ -v

# Run fast tests (unit + integration)
test-fast:
	pipenv run pytest tests/unit/ tests/integration/ -v

# Run slow tests (functional)
test-slow:
	pipenv run pytest tests/functional/ -v

# Run all tests with coverage
test-coverage:
	pipenv run pytest tests/ --cov=src --cov-report=html --cov-report=term-missing

# Run tests with specific markers
test-api:
	pipenv run pytest tests/ -m api -v

test-bitcoin:
	pipenv run pytest tests/ -m bitcoin -v

test-brc20:
	pipenv run pytest tests/ -m brc20 -v

test-database:
	pipenv run pytest tests/ -m database -v

# Clean up temporary files
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf .pytest_cache/
	rm -rf test.db

# Install dependencies
install:
	pipenv install --dev

# Development utilities
lint:
	pipenv run black src/ tests/
	pipenv run flake8 src/ tests/
	pipenv run isort src/ tests/

format:
	pipenv run black src/ tests/
	pipenv run isort src/ tests/

# Quick test for CI/CD
test-ci:
	pipenv run pytest tests/ --tb=short --maxfail=10 
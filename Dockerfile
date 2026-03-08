# Multi-stage Dockerfile for Universal BRC-20 Indexer
# Stage 1: Builder
FROM python:3.11-slim as builder

# Install system dependencies for building
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gcc \
    pkg-config \
    libsecp256k1-dev \
    && rm -rf /var/lib/apt/lists/*

# Install pipenv
RUN pip install pipenv

# Copy dependency files
COPY Pipfile Pipfile.lock ./

# Install Python dependencies
RUN pipenv install --deploy --system

# Stage 2: Runtime
FROM python:3.11-slim as runtime

# Create non-root user
RUN groupadd -r indexer && useradd -r -g indexer indexer

# Create home directory for indexer user and set permissions
RUN mkdir -p /home/indexer && chown -R indexer:indexer /home/indexer
ENV HOME=/home/indexer

# Install runtime dependencies only (no libsecp256k1 package in slim; copy from builder)
RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy libsecp256k1 from builder (not always in slim repo; builder has it via libsecp256k1-dev)
COPY --from=builder /usr/lib/x86_64-linux-gnu/libsecp256k1.so* /usr/lib/x86_64-linux-gnu/

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create working directory
WORKDIR /app

# Copy source code and Alembic config (required for migrate service)
COPY src/ ./src/
COPY tests/ ./tests/
COPY alembic/ ./alembic/
COPY run.py ./
# alembic.ini must be in project root at build time; required for migrate service
COPY alembic.ini ./alembic.ini


# Create necessary directories
RUN mkdir -p logs temp_docs && \
    chown -R indexer:indexer /app

# Switch to non-root user
USER indexer

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/v1/indexer/brc20/health || exit 1

# Expose port
EXPOSE 8080

# Default command
CMD ["python", "run.py", "--continuous"] 
#!/bin/bash

# OPI Database Setup Script
# This script sets up the OPI database tables for the Simplicity Indexer

echo "🚀 Setting up OPI database tables..."

# Load environment variables from .env file
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env file..."
    set -a
    source .env
    set +a
fi

# Check if DATABASE_URL is set
if [ -z "$DATABASE_URL" ]; then
    echo "❌ Error: DATABASE_URL environment variable is not set"
    echo "Please set DATABASE_URL in your .env file or environment"
    exit 1
fi

# Extract database connection info from DATABASE_URL
DB_HOST=$(echo $DATABASE_URL | sed -n 's/.*@\([^:]*\).*/\1/p')
DB_PORT=$(echo $DATABASE_URL | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
DB_NAME=$(echo $DATABASE_URL | sed -n 's/.*\/\([^?]*\).*/\1/p')
DB_USER=$(echo $DATABASE_URL | sed -n 's/.*:\/\/\([^:]*\):.*/\1/p')
DB_PASS=$(echo $DATABASE_URL | sed -n 's/.*:\/\/[^:]*:\([^@]*\)@.*/\1/p')

echo "📊 Database Info:"
echo "  Host: $DB_HOST"
echo "  Port: $DB_PORT"
echo "  Database: $DB_NAME"
echo "  User: $DB_USER"

# Run the SQL script
echo "🔧 Creating OPI tables..."
psql "$DATABASE_URL" -f setup_opi_database.sql

if [ $? -eq 0 ]; then
    echo "✅ OPI database setup completed successfully!"
    echo ""
    echo "📋 Available OPI endpoints:"
    echo "  GET /v1/indexer/brc20/opi                    # List all OPIs"
    echo "  GET /v1/indexer/brc20/opi/{opi_id}          # Get OPI details"
    echo "  GET /v1/indexer/brc20/opi/operations/{txid}  # Get OPI operations for tx"
    echo "  GET /v1/indexer/brc20/opi/operations/block/{block_height}  # Get OPI operations in block"
    echo "  GET /v1/indexer/brc20/opi/no_return/transfers/{txid}  # Get no_return data"
    echo ""
    echo "🎯 Next steps:"
    echo "  1. Start the indexer: pipenv run python -m src.main"
    echo "  2. Test the API: curl http://localhost:8081/v1/indexer/brc20/opi"
    echo "  3. Run tests: pipenv run pytest tests/test_opi_*.py"
else
    echo "❌ Error: Failed to create OPI tables"
    echo "Please check your database connection and permissions"
    exit 1
fi 
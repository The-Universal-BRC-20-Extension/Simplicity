#!/bin/bash

# Quick Reset Script for Simplicity Indexer
# This is a simple wrapper around the Python reset script

echo "🔄 Quick Reset Script for Simplicity Indexer"
echo "=========================================="

# Check if pipenv is available
if ! command -v pipenv &> /dev/null; then
    echo "❌ Error: pipenv is not installed or not in PATH"
    echo "Please install pipenv: pip install pipenv"
    exit 1
fi

# Check if the reset script exists
if [ ! -f "reset_and_restart.py" ]; then
    echo "❌ Error: reset_and_restart.py not found"
    exit 1
fi

# Run the reset script with all arguments passed through
echo "🚀 Running reset script..."
pipenv run python reset_and_restart.py "$@"

echo "✅ Quick reset script completed" 
#!/bin/bash

# Start Simplicity Indexer with logging
# This script starts the indexer and redirects output to log files

echo "🚀 Starting Simplicity Indexer with logging..."

# Create logs directory
mkdir -p logs

# Generate timestamp for log files
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="logs/indexer_${TIMESTAMP}.log"
ERROR_LOG="logs/indexer_${TIMESTAMP}_error.log"

echo "📝 Logs will be written to:"
echo "  📄 Main log: $LOG_FILE"
echo "  ❌ Error log: $ERROR_LOG"

# Stop any existing processes
echo "🛑 Stopping existing processes..."
pkill -f "run.py" 2>/dev/null
sleep 2

# Start the indexer with logging
echo "🚀 Starting indexer in continuous mode..."
pipenv run python run.py --continuous > "$LOG_FILE" 2> "$ERROR_LOG" &

# Get the process ID
INDEXER_PID=$!
echo "✅ Indexer started with PID: $INDEXER_PID"
echo "📊 Process info:"
ps -p $INDEXER_PID -o pid,ppid,cmd

echo ""
echo "📋 Log file locations:"
echo "  📄 Main log: $LOG_FILE"
echo "  ❌ Error log: $ERROR_LOG"
echo ""
echo "🔍 To monitor logs in real-time:"
echo "  tail -f $LOG_FILE"
echo "  tail -f $ERROR_LOG"
echo ""
echo "🛑 To stop the indexer:"
echo "  kill $INDEXER_PID"
echo "  or: pkill -f run.py" 
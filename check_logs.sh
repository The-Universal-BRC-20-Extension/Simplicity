#!/bin/bash

# Check and monitor Simplicity Indexer logs

echo "📋 Simplicity Indexer Log Checker"
echo "=================================="

# Check if logs directory exists
if [ ! -d "logs" ]; then
    echo "❌ No logs directory found"
    echo "💡 Run ./start_with_logs.sh to start with logging"
    exit 1
fi

# List all log files
echo "📁 Available log files:"
ls -la logs/ 2>/dev/null | grep -E "\.(log|txt)$" || echo "  No log files found"

# Check for recent log files
RECENT_LOGS=$(find logs/ -name "*.log" -mtime -1 2>/dev/null | head -5)
if [ -n "$RECENT_LOGS" ]; then
    echo ""
    echo "🕒 Recent log files (last 24 hours):"
    echo "$RECENT_LOGS"
    
    # Show last few lines of the most recent log
    LATEST_LOG=$(ls -t logs/*.log 2>/dev/null | head -1)
    if [ -n "$LATEST_LOG" ]; then
        echo ""
        echo "📄 Latest log file: $LATEST_LOG"
        echo "📊 File size: $(du -h "$LATEST_LOG" | cut -f1)"
        echo "🕒 Last modified: $(stat -c %y "$LATEST_LOG")"
        echo ""
        echo "📋 Last 20 lines:"
        echo "=================================="
        tail -20 "$LATEST_LOG"
        echo "=================================="
    fi
else
    echo ""
    echo "⚠️  No recent log files found"
fi

# Check for running processes
echo ""
echo "🔄 Running processes:"
RUNNING_PROCESSES=$(ps aux | grep -E "(run\.py|uvicorn)" | grep -v grep)
if [ -n "$RUNNING_PROCESSES" ]; then
    echo "$RUNNING_PROCESSES"
else
    echo "  No indexer processes found"
fi

echo ""
echo "🔍 Commands to monitor logs:"
echo "  tail -f logs/indexer_*.log    # Monitor main logs"
echo "  tail -f logs/*_error.log      # Monitor error logs"
echo "  ./check_logs.sh               # Run this script again" 
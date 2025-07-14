# 📋 Log Management Guide for Simplicity Indexer

This guide explains how to manage logs for the Simplicity Indexer, including automatic logging during reset operations.

---

## 🚀 **Automatic Logging (Recommended)**

The `reset_and_restart.py` script now includes **automatic logging** by default. When you run the reset script, it will:

1. **Create timestamped log files** in the `logs/` directory
2. **Capture all output** from the indexer process
3. **Separate stdout and stderr** into different files
4. **Provide real-time log monitoring** commands

### **Usage with Automatic Logging**

```bash
# Full reset with automatic logging (default)
pipenv run python reset_and_restart.py

# Reset without creating log files (output to terminal only)
pipenv run python reset_and_restart.py --no-logs

# Quick reset using the wrapper script
./quick_reset.sh
```

### **Log Files Created**

When automatic logging is enabled, the script creates:

- **Main Log**: `logs/indexer_YYYYMMDD_HHMMSS.log` (stdout)
- **Error Log**: `logs/indexer_YYYYMMDD_HHMMSS_error.log` (stderr)  
- **Combined Log**: `logs/indexer_YYYYMMDD_HHMMSS_combined.log` (both)

### **Log Monitoring Commands**

After starting the indexer, the script will show you useful commands:

```bash
# Watch main log in real-time
tail -f logs/indexer_20241201_143022.log

# Watch error log in real-time  
tail -f logs/indexer_20241201_143022_error.log

# Watch combined log in real-time
tail -f logs/indexer_20241201_143022_combined.log

# View last 50 lines of main log
tail -50 logs/indexer_20241201_143022.log

# Search for errors in combined log
grep -i error logs/indexer_20241201_143022_combined.log

# Check log file sizes
ls -lh logs/indexer_20241201_143022*
```

---

## 🔧 **Manual Log Management**

If you need to start the indexer manually with logging:

### **1. Start with Logs Script**

```bash
# Start indexer with automatic logging
./start_with_logs.sh

# Start with custom log prefix
./start_with_logs.sh my_indexer
```

### **2. Check Logs Script**

```bash
# Check current logs
./check_logs.sh

# Monitor logs in real-time
./check_logs.sh --watch

# Show log statistics
./check_logs.sh --stats
```

---

## 📊 **Log File Structure**

### **Main Log (`indexer_*.log`)**
Contains normal application output:
- Startup messages
- Processing status
- API requests
- General information

### **Error Log (`indexer_*_error.log`)**
Contains error messages and warnings:
- Exception traces
- Error responses
- Warning messages
- Debug information

### **Combined Log (`indexer_*_combined.log`)**
Contains both stdout and stderr with timestamps:
- All output in chronological order
- Timestamped entries
- Error messages marked with "ERROR:" prefix

---

## 🛠️ **Log Management Commands**

### **View Logs**

```bash
# View latest log files
ls -la logs/

# View last 100 lines of main log
tail -100 logs/indexer_*.log | tail -100

# View all error messages
grep -i error logs/indexer_*_combined.log

# View startup messages
grep -i "starting\|started" logs/indexer_*_combined.log
```

### **Monitor Logs**

```bash
# Watch main log in real-time
tail -f logs/indexer_*.log

# Watch error log in real-time
tail -f logs/indexer_*_error.log

# Watch combined log in real-time
tail -f logs/indexer_*_combined.log

# Monitor multiple logs simultaneously
tail -f logs/indexer_*.log logs/indexer_*_error.log
```

### **Search Logs**

```bash
# Search for specific terms
grep "API" logs/indexer_*_combined.log
grep "ERROR" logs/indexer_*_combined.log
grep "WARNING" logs/indexer_*_combined.log

# Search with context (3 lines before/after)
grep -A 3 -B 3 "error" logs/indexer_*_combined.log

# Search in last hour
find logs/ -name "indexer_*.log" -newermt "1 hour ago" -exec grep "error" {} \;
```

### **Log Maintenance**

```bash
# Check log file sizes
du -h logs/*.log

# Compress old logs
gzip logs/indexer_*.log

# Remove logs older than 7 days
find logs/ -name "indexer_*.log" -mtime +7 -delete

# Archive logs by date
mkdir logs/archive/$(date +%Y%m)
mv logs/indexer_*.log logs/archive/$(date +%Y%m)/
```

---

## 🔍 **Troubleshooting**

### **Common Issues**

1. **No logs created**: Check if `logs/` directory exists and is writable
2. **Empty log files**: Indexer may not be producing output yet
3. **Permission errors**: Ensure write permissions on `logs/` directory
4. **Large log files**: Use log rotation or compression

### **Debug Commands**

```bash
# Check if indexer is running
ps aux | grep run.py

# Check log directory permissions
ls -la logs/

# Check available disk space
df -h .

# Check log file timestamps
ls -la logs/indexer_*.log
```

### **Log Analysis**

```bash
# Count error occurrences
grep -c "ERROR" logs/indexer_*_combined.log

# Find most common error types
grep "ERROR" logs/indexer_*_combined.log | cut -d' ' -f4- | sort | uniq -c | sort -nr

# Check for specific error patterns
grep -E "(Exception|Error|Failed)" logs/indexer_*_combined.log

# Monitor API response times
grep "API.*response" logs/indexer_*_combined.log | tail -20
```

---

## 📈 **Performance Monitoring**

### **Log File Growth**

```bash
# Monitor log file size growth
watch -n 5 'ls -lh logs/indexer_*.log'

# Check log rotation needs
find logs/ -name "*.log" -size +100M
```

### **Error Rate Monitoring**

```bash
# Count errors per hour
grep "$(date '+%Y-%m-%d %H')" logs/indexer_*_combined.log | grep -c ERROR

# Monitor error trends
for hour in {0..23}; do
    echo "Hour $hour: $(grep "$(date '+%Y-%m-%d') $hour:" logs/indexer_*_combined.log | grep -c ERROR) errors"
done
```

---

## 🎯 **Best Practices**

1. **Use automatic logging** with `reset_and_restart.py` for production
2. **Monitor logs regularly** using the provided commands
3. **Archive old logs** to prevent disk space issues
4. **Search for patterns** in errors to identify recurring issues
5. **Set up log rotation** for long-running deployments
6. **Use `--no-logs`** only for debugging or development

---

## 📝 **Quick Reference**

| Command | Description |
|---------|-------------|
| `pipenv run python reset_and_restart.py` | Reset with automatic logging |
| `pipenv run python reset_and_restart.py --no-logs` | Reset without log files |
| `tail -f logs/indexer_*.log` | Watch main log in real-time |
| `grep ERROR logs/indexer_*_combined.log` | Find all errors |
| `./check_logs.sh --watch` | Monitor all logs |
| `./start_with_logs.sh` | Start indexer with manual logging |

---

**Note**: The automatic logging feature is now integrated into the reset script, making it the recommended approach for production use. Manual logging scripts are still available for specific use cases. 
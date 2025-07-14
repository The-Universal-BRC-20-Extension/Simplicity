# 🔄 Database Reset and Restart Guide

## Quick Usage

### Full Reset and Restart (Recommended)
```bash
pipenv run python reset_and_restart.py
```

This will:
1. ✅ Create a backup of your current database
2. 🛑 Stop any running indexer processes
3. 🔄 Run database migrations
4. 🗑️ Truncate all tables (clear all data)
5. 🔧 Reinitialize required data (OPI configurations)
6. 🚀 Start the indexer in continuous mode
7. 🏥 Check API health

### Options

#### Backup Only
```bash
pipenv run python reset_and_restart.py --backup-only
```
Only creates a backup, doesn't reset anything.

#### Skip Backup
```bash
pipenv run python reset_and_restart.py --no-backup
```
Skip backup creation (not recommended for production).

#### Dry Run
```bash
pipenv run python reset_and_restart.py --dry-run
```
Show what would be done without actually doing it.

#### Reset Without Restart
```bash
pipenv run python reset_and_restart.py --no-restart
```
Reset the database but don't restart the indexer.

#### Skip Migrations (if tables already exist)
```bash
pipenv run python reset_and_restart.py --skip-migrations
```
Skip database migrations if tables already exist (useful after first run).

## What Gets Reset

### Tables Cleared
- All BRC-20 operations
- All balances
- All deployments
- All OPI operations
- All processed blocks
- All OPI configurations (then recreated)

### Data Reinitialized
- OPI-000 configuration (enabled, version 1.0)
- Database schema (via migrations)

## Backup Location
Backups are saved in the `backups/` directory with timestamps:
```
backups/backup_20241201_143022.sql
```

## Health Check
After restart, the script checks:
- API health endpoint: `http://localhost:8081/v1/indexer/brc20/health`
- API documentation: `http://localhost:8081/docs`

## Troubleshooting

### If the script fails:
1. Check your `.env` file has correct database settings
2. Ensure you have `pg_dump` installed (for PostgreSQL)
3. Make sure no other processes are using the database
4. Check the logs for specific error messages

### If you get "DuplicateTable" errors:
This happens when tables already exist but Alembic tries to create them again. Use:
```bash
pipenv run python reset_and_restart.py --skip-migrations
```
Or run the script again - it should handle this automatically now.

### To stop the indexer manually:
```bash
pkill -f run.py
```

### To restore from backup:
```bash
# For PostgreSQL
psql your_database < backups/backup_YYYYMMDD_HHMMSS.sql

# For SQLite
cp backups/backup_YYYYMMDD_HHMMSS.sql test.db
```

## Safety Features
- ✅ Automatic backup before any changes
- ✅ Dry-run mode to preview changes
- ✅ Process cleanup before restart
- ✅ Health checks after restart
- ✅ Error handling and rollback on failures

## Production Use
For production environments:
1. Always use the default mode (with backup)
2. Test with `--dry-run` first
3. Monitor the logs during execution
4. Verify the health check passes
5. Keep backups in a safe location 
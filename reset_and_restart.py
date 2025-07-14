#!/usr/bin/env python3
"""
Database Reset and Restart Script for Simplicity Indexer

This script performs the following operations:
1. Creates a backup of the current database
2. Truncates all tables (clears all data)
3. Reinitializes required data (OPI configurations, etc.)
4. Restarts the indexer in continuous mode with automatic logging

Usage:
    python reset_and_restart.py [--backup-only] [--no-backup] [--dry-run] [--no-logs]
"""

import sys
import os
import subprocess
import time
import argparse
import datetime
import signal
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import MetaData, text
from src.database.connection import engine
from src.models.opi_configuration import OPIConfiguration
from src.models.base import Base


def get_database_info():
    """Extract database connection info from DATABASE_URL"""
    from src.config import settings
    
    db_url = settings.DATABASE_URL
    if db_url.startswith('postgresql://'):
        # Extract components from PostgreSQL URL
        parts = db_url.replace('postgresql://', '').split('@')
        if len(parts) == 2:
            auth, rest = parts
            user_pass = auth.split(':')
            if len(user_pass) == 2:
                user, password = user_pass
            else:
                user = auth
                password = ""
            
            host_port_db = rest.split('/')
            if len(host_port_db) == 2:
                host_port, database = host_port_db
                host_port_parts = host_port.split(':')
                if len(host_port_parts) == 2:
                    host, port = host_port_parts
                else:
                    host = host_port_parts[0]
                    port = "5432"
            else:
                host = "localhost"
                port = "5432"
                database = "brc20_indexer"
            
            return {
                'host': host,
                'port': port,
                'database': database,
                'user': user,
                'password': password,
                'url': db_url
            }
    
    # Fallback for SQLite or other databases
    return {
        'host': 'localhost',
        'port': '5432',
        'database': 'brc20_indexer',
        'user': 'indexer',
        'password': '',
        'url': db_url
    }


def setup_logging():
    """Setup logging directory and return log file paths"""
    # Create logs directory
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Generate timestamp for log files
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Create log file paths
    main_log = logs_dir / f"indexer_{timestamp}.log"
    error_log = logs_dir / f"indexer_{timestamp}_error.log"
    combined_log = logs_dir / f"indexer_{timestamp}_combined.log"
    
    return {
        'main_log': str(main_log),
        'error_log': str(error_log),
        'combined_log': str(combined_log),
        'timestamp': timestamp
    }


def create_backup():
    """Create a backup of the current database"""
    print("📦 Creating database backup...")
    
    db_info = get_database_info()
    
    # Create backup directory
    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    
    # Generate backup filename with timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"backup_{timestamp}.sql"
    
    try:
        if db_info['url'].startswith('postgresql://'):
            # PostgreSQL backup using pg_dump
            cmd = [
                'pg_dump',
                f"--host={db_info['host']}",
                f"--port={db_info['port']}",
                f"--username={db_info['user']}",
                f"--dbname={db_info['database']}",
                "--no-password",  # Use .pgpass or environment
                "--verbose",
                "--clean",
                "--no-owner",
                "--no-privileges",
                f"--file={backup_file}"
            ]
            
            # Set password environment variable
            env = os.environ.copy()
            if db_info['password']:
                env['PGPASSWORD'] = db_info['password']
            
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✅ Backup created successfully: {backup_file}")
                print(f"📊 Backup size: {backup_file.stat().st_size / 1024:.1f} KB")
                return str(backup_file)
            else:
                print(f"❌ Backup failed: {result.stderr}")
                return None
        else:
            # SQLite backup (just copy the file)
            if os.path.exists("test.db"):
                import shutil
                shutil.copy2("test.db", backup_file)
                print(f"✅ SQLite backup created: {backup_file}")
                return str(backup_file)
            else:
                print("⚠️  No SQLite database file found to backup")
                return None
                
    except Exception as e:
        print(f"❌ Error creating backup: {e}")
        return None


def truncate_database():
    """Truncate all tables in the database"""
    print("🔄 Truncating database...")
    
    try:
        # Reflect all tables
        meta = MetaData()
        meta.reflect(bind=engine)
        
        # Delete all data from all tables in reverse dependency order
        with engine.begin() as conn:
            for table in reversed(meta.sorted_tables):
                print(f"  🗑️  Clearing table: {table.name}")
                conn.execute(table.delete())
            
            # Also clear the alembic_version table to reset migration state
            try:
                conn.execute(text("DELETE FROM alembic_version"))
                print("  🗑️  Cleared alembic_version table")
            except Exception as e:
                print(f"  ⚠️  Could not clear alembic_version: {e}")
        
        print("✅ Database truncated successfully!")
        print(f"📊 Cleared {len(meta.sorted_tables)} tables")
        return True
        
    except Exception as e:
        print(f"❌ Error truncating database: {e}")
        return False


def reinitialize_data():
    """Reinitialize required data (OPI configurations, etc.)"""
    print("🔧 Reinitializing required data...")
    
    try:
        from sqlalchemy.orm import sessionmaker
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        
        with SessionLocal() as session:
            # Create OPI-000 configuration
            opi_config = OPIConfiguration(
                opi_id="OPI-000",
                is_enabled=True,
                version="1.0",
                description="No Return Operations",
                configuration={"enabled": True}
            )
            
            # Check if it already exists
            existing = session.query(OPIConfiguration).filter_by(opi_id="OPI-000").first()
            if existing:
                print("  ✅ OPI-000 configuration already exists")
            else:
                session.add(opi_config)
                session.commit()
                print("  ✅ OPI-000 configuration created")
            
            # Add any other required initial data here
            # For example, you might want to add other OPI configurations
            
        print("✅ Data reinitialization completed!")
        return True
        
    except Exception as e:
        print(f"❌ Error reinitializing data: {e}")
        return False


def run_migrations():
    """Run database migrations"""
    print("🔄 Running database migrations...")
    
    try:
        # First check current migration status
        status_result = subprocess.run(
            ["pipenv", "run", "alembic", "current"],
            capture_output=True,
            text=True,
            cwd=os.getcwd()
        )
        
        print(f"📊 Current migration status: {status_result.stdout.strip()}")
        
        # Run migrations with more detailed output
        result = subprocess.run(
            ["pipenv", "run", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd=os.getcwd()
        )
        
        if result.returncode == 0:
            print("✅ Database migrations completed successfully!")
            return True
        else:
            print(f"❌ Migration failed: {result.stderr}")
            print(f"📋 Migration output: {result.stdout}")
            
            # If it's a duplicate table error, that's actually okay
            if "DuplicateTable" in result.stderr or "already exists" in result.stderr:
                print("⚠️  Tables already exist - this is normal after a reset")
                print("✅ Migration step completed (tables already present)")
                
                # Stamp the database with the current version
                stamp_result = subprocess.run(
                    ["pipenv", "run", "alembic", "stamp", "head"],
                    capture_output=True,
                    text=True,
                    cwd=os.getcwd()
                )
                
                if stamp_result.returncode == 0:
                    print("✅ Database stamped with current migration version")
                else:
                    print(f"⚠️  Could not stamp database: {stamp_result.stderr}")
                
                return True
            elif "No such file or directory" in result.stderr or "command not found" in result.stderr:
                print("❌ Alembic command not found. Please ensure pipenv is set up correctly.")
                return False
            else:
                print("❌ Unknown migration error. Check the logs above.")
                return False
            
    except Exception as e:
        print(f"❌ Error running migrations: {e}")
        return False


def stop_running_processes():
    """Stop only the indexer process running on port 8081"""
    print("🛑 Stopping indexer process on port 8081...")
    
    try:
        # Find processes using port 8081
        result = subprocess.run(
            ["lsof", "-ti:8081"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            print(f"📊 Found {len(pids)} process(es) using port 8081")
            
            for pid in pids:
                if pid.strip():
                    print(f"  🗑️  Stopping process {pid}")
                    subprocess.run(["kill", "-TERM", pid.strip()], capture_output=True)
            
            # Wait a moment for processes to stop
            time.sleep(2)
            
            # Check if processes are still running
            check_result = subprocess.run(
                ["lsof", "-ti:8081"],
                capture_output=True,
                text=True
            )
            
            if check_result.returncode == 0 and check_result.stdout.strip():
                print("⚠️  Some processes still running, force killing...")
                for pid in check_result.stdout.strip().split('\n'):
                    if pid.strip():
                        subprocess.run(["kill", "-KILL", pid.strip()], capture_output=True)
            
            print("✅ Indexer process on port 8081 stopped")
            return True
        else:
            print("ℹ️  No processes found running on port 8081")
            return True
        
    except Exception as e:
        print(f"⚠️  Warning: Could not stop processes on port 8081: {e}")
        return False


def start_indexer_continuous(enable_logs=True):
    """Start the indexer in continuous mode with optional logging"""
    print("🚀 Starting indexer in continuous mode...")
    
    try:
        if enable_logs:
            # Setup logging
            log_info = setup_logging()
            
            print(f"📝 Logs will be written to:")
            print(f"  📄 Main log: {log_info['main_log']}")
            print(f"  ❌ Error log: {log_info['error_log']}")
            print(f"  📋 Combined log: {log_info['combined_log']}")
            
            # Start the indexer in the background with logging
            with open(log_info['main_log'], 'w') as stdout_file, \
                 open(log_info['error_log'], 'w') as stderr_file, \
                 open(log_info['combined_log'], 'w') as combined_file:
                
                # Write startup message to logs
                startup_msg = f"[{datetime.datetime.now()}] Starting Simplicity Indexer in continuous mode\n"
                stdout_file.write(startup_msg)
                stderr_file.write(startup_msg)
                combined_file.write(startup_msg)
                
                # Start the process
                process = subprocess.Popen(
                    ["pipenv", "run", "python", "run.py", "--continuous"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                # Create a thread to handle log writing
                import threading
                
                def log_writer():
                    while process.poll() is None:
                        # Read stdout
                        stdout_line = process.stdout.readline()
                        if stdout_line:
                            stdout_file.write(f"[{datetime.datetime.now()}] {stdout_line}")
                            combined_file.write(f"[{datetime.datetime.now()}] {stdout_line}")
                            stdout_file.flush()
                            combined_file.flush()
                        
                        # Read stderr
                        stderr_line = process.stderr.readline()
                        if stderr_line:
                            stderr_file.write(f"[{datetime.datetime.now()}] {stderr_line}")
                            combined_file.write(f"[{datetime.datetime.now()}] ERROR: {stderr_line}")
                            stderr_file.flush()
                            combined_file.flush()
                
                # Start the log writer thread
                log_thread = threading.Thread(target=log_writer, daemon=True)
                log_thread.start()
                
        else:
            # Start without logging (direct to terminal)
            process = subprocess.Popen(
                ["pipenv", "run", "python", "run.py", "--continuous"],
                text=True
            )
            log_info = None
        
        # Wait a moment to see if it starts successfully
        time.sleep(3)
        
        if process.poll() is None:
            print("✅ Indexer started successfully in continuous mode")
            print(f"📊 Process ID: {process.pid}")
            if enable_logs and log_info:
                print(f"📄 Log files created:")
                print(f"  📄 Main: {log_info['main_log']}")
                print(f"  ❌ Error: {log_info['error_log']}")
                print(f"  📋 Combined: {log_info['combined_log']}")
            return process, log_info
        else:
            # Read error log to see what went wrong
            if enable_logs and log_info:
                try:
                    with open(log_info['error_log'], 'r') as f:
                        error_content = f.read()
                    print(f"❌ Indexer failed to start. Check error log: {log_info['error_log']}")
                    print(f"📋 Error content: {error_content[:500]}...")
                except:
                    print("❌ Indexer failed to start (could not read error log)")
            else:
                print("❌ Indexer failed to start")
            return None, None
            
    except Exception as e:
        print(f"❌ Error starting indexer: {e}")
        return None, None


def check_health():
    """Check if the API is responding on port 8081"""
    print("🏥 Checking API health on port 8081...")
    
    try:
        import requests
        import time
        
        # Wait a bit for the API to start
        time.sleep(5)
        
        response = requests.get("http://localhost:8081/v1/indexer/brc20/health", timeout=10)
        
        if response.status_code == 200:
            print("✅ API is healthy and responding on port 8081")
            return True
        else:
            print(f"❌ API health check failed on port 8081: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Health check failed on port 8081: {e}")
        return False


def show_log_commands(log_info):
    """Show useful log monitoring commands"""
    if not log_info:
        return
    
    print("\n📋 Useful log monitoring commands:")
    print("=" * 50)
    print(f"# Watch main log in real-time:")
    print(f"tail -f {log_info['main_log']}")
    print()
    print(f"# Watch error log in real-time:")
    print(f"tail -f {log_info['error_log']}")
    print()
    print(f"# Watch combined log in real-time:")
    print(f"tail -f {log_info['combined_log']}")
    print()
    print(f"# View last 50 lines of main log:")
    print(f"tail -50 {log_info['main_log']}")
    print()
    print(f"# Search for errors in combined log:")
    print(f"grep -i error {log_info['combined_log']}")
    print()
    print(f"# Check log file sizes:")
    print(f"ls -lh {log_info['main_log']} {log_info['error_log']} {log_info['combined_log']}")


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Reset and restart Simplicity Indexer")
    parser.add_argument("--backup-only", action="store_true", help="Only create backup, don't reset")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup creation")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without doing it")
    parser.add_argument("--no-restart", action="store_true", help="Don't restart the indexer")
    parser.add_argument("--skip-migrations", action="store_true", help="Skip database migrations (use if tables already exist)")
    parser.add_argument("--no-logs", action="store_true", help="Don't create log files (output to terminal only)")
    
    args = parser.parse_args()
    
    print("🔄 Simplicity Indexer - Database Reset and Restart")
    print("=" * 60)
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        print("=" * 60)
    
    # Step 1: Create backup (unless skipped)
    backup_file = None
    if not args.no_backup:
        if not args.dry_run:
            backup_file = create_backup()
        else:
            print("📦 Would create database backup")
    
    if args.backup_only:
        print("✅ Backup completed. Exiting.")
        return
    
    # Step 2: Stop running processes
    if not args.dry_run:
        stop_running_processes()
    else:
        print("🛑 Would stop running processes")
    
    # Step 3: Run migrations
    if not args.dry_run:
        if args.skip_migrations:
            print("⏭️  Skipping database migrations (tables already exist)")
        elif not run_migrations():
            print("❌ Migration failed. Exiting.")
            return
    else:
        if args.skip_migrations:
            print("⏭️  Would skip database migrations")
        else:
            print("🔄 Would run database migrations")
    
    # Step 4: Truncate database
    if not args.dry_run:
        if not truncate_database():
            print("❌ Database truncation failed. Exiting.")
            return
    else:
        print("🔄 Would truncate database")
    
    # Step 5: Reinitialize data
    if not args.dry_run:
        if not reinitialize_data():
            print("❌ Data reinitialization failed. Exiting.")
            return
    else:
        print("🔧 Would reinitialize required data")
    
    # Step 6: Start indexer (unless skipped)
    if not args.no_restart:
        if not args.dry_run:
            process, log_info = start_indexer_continuous(enable_logs=not args.no_logs)
            if process:
                print("\n🎉 Reset and restart completed successfully!")
                print("=" * 60)
                print("📊 Indexer is now running in continuous mode on port 8081")
                print("🌐 API should be available at: http://localhost:8081")
                print("📚 API docs available at: http://localhost:8081/docs")
                print("=" * 60)
                
                # Check health
                if check_health():
                    print("✅ All systems operational on port 8081!")
                else:
                    print("⚠️  API health check failed on port 8081 - check logs for details")
                
                print(f"\n💾 Backup file: {backup_file}" if backup_file else "")
                print("🔄 To stop the indexer on port 8081, use: lsof -ti:8081 | xargs kill")
                
                # Show log commands if logging is enabled
                if not args.no_logs and log_info:
                    show_log_commands(log_info)
            else:
                print("❌ Failed to start indexer")
        else:
            print("🚀 Would start indexer in continuous mode")
            if not args.no_logs:
                print("📝 Would create log files")
    else:
        print("✅ Reset completed (indexer not restarted)")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main() 
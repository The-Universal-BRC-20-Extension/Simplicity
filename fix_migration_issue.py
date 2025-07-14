#!/usr/bin/env python3
"""
Quick fix for migration issues.
This script stamps the database with the current migration version.
"""

import subprocess
import sys

def fix_migration():
    """Fix migration issues by stamping the database"""
    print("🔧 Fixing migration issues...")
    
    try:
        # Stamp the database with the current version
        result = subprocess.run(
            ["pipenv", "run", "alembic", "stamp", "head"],
            capture_output=True,
            text=True,
            cwd="."
        )
        
        if result.returncode == 0:
            print("✅ Database stamped successfully!")
            print("📊 Migration version set to current head")
            return True
        else:
            print(f"❌ Stamping failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error fixing migration: {e}")
        return False

if __name__ == "__main__":
    fix_migration() 
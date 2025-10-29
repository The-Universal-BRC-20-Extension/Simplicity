#!/bin/bash
# This script saves the database to a file in the backups directory
DB_NAME=brc20
DATETIME=$(date +%Y%m%d_%H%M%S)
pg_dump --format=plain --no-owner --no-privileges --dbname=$DB_NAME > backups/{$DB_NAME}_{$DATETIME}.sql

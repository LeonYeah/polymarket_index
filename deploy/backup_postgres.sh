#!/usr/bin/env bash
set -euo pipefail

backup_dir=/var/backups/polymarket
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
umask 077
mkdir -p "$backup_dir"
/usr/bin/pg_dump --format=custom --no-owner --no-acl \
  --file="$backup_dir/polymarket-$timestamp.dump" polymarket
find "$backup_dir" -type f -name 'polymarket-*.dump' -mtime +14 -delete

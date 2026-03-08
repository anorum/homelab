#!/bin/bash
# Homelab backup script — runs on Mac Mini, pulls data from Pis
# Scheduled via launchd (~/Library/LaunchAgents/com.homelab.backup.plist)

set -euo pipefail

BACKUP_ROOT="$HOME/backups/homelab"
BACKUP_DIR="$BACKUP_ROOT/$(date +%Y-%m-%d)"
LOG_FILE="$BACKUP_ROOT/backup.log"
SSH_KEY="$HOME/.ssh/rpi_key"
SSH_USER="anorum"
MASTER="192.168.1.101"
WORKER="192.168.1.102"
RETENTION_DAYS=7

SSH_OPTS="-i $SSH_KEY -o ConnectTimeout=10 -o StrictHostKeyChecking=no"

mkdir -p "$BACKUP_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

errors=0

log "=== Backup started ==="

# 1. Mealie data (High priority)
log "Backing up Mealie data from swagman-2..."
if rsync -avz -e "ssh $SSH_OPTS" "$SSH_USER@$WORKER:/mnt/hd/mealie/" "$BACKUP_DIR/mealie/" >> "$LOG_FILE" 2>&1; then
    log "Mealie backup complete"
else
    log "ERROR: Mealie backup failed"
    errors=$((errors + 1))
fi

# 2. Authentik PostgreSQL dump (High priority)
log "Backing up Authentik database from swagman-1..."
if ssh $SSH_OPTS "$SSH_USER@$MASTER" \
    "sudo kubectl exec -n authentik authentik-postgresql-0 -- bash -c 'PGPASSWORD=\$(cat /opt/bitnami/postgresql/secrets/postgresql-password) pg_dump -U authentik authentik'" \
    > "$BACKUP_DIR/authentik-db.sql" 2>> "$LOG_FILE"; then
    size=$(wc -c < "$BACKUP_DIR/authentik-db.sql" | tr -d ' ')
    if [ "$size" -gt 1000 ]; then
        log "Authentik DB backup complete ($size bytes)"
    else
        log "ERROR: Authentik DB dump suspiciously small ($size bytes)"
        errors=$((errors + 1))
    fi
else
    log "ERROR: Authentik DB backup failed"
    errors=$((errors + 1))
fi

# 3. Retention — delete backups older than $RETENTION_DAYS days
log "Cleaning up backups older than $RETENTION_DAYS days..."
find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" -mtime +$RETENTION_DAYS -exec rm -rf {} \; 2>> "$LOG_FILE"

# Summary
if [ $errors -eq 0 ]; then
    log "=== Backup completed successfully ==="
else
    log "=== Backup completed with $errors error(s) ==="
fi

exit $errors

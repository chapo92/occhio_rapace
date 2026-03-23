# Auto-Backup & Rotation System

## Overview
Automatic daily backups with weekly USB rotation for disaster recovery.

## Setup

### 1. Initial Configuration
Edit `backup_config.json`:
- Set paths to your database
- Configure email alerts (optional)
- Set backup time (default: midnight)

### 2. Create Directories
```bash
mkdir -p backups
mkdir -p logs
```

### 3. Enable Scheduler
Add to your main.py or use cron:

**Option A: Python (automatic)**
```python
from scripts.backup.backup_scheduler import BackupScheduler

scheduler = BackupScheduler()
scheduler.schedule_daily_backup(hour=0, minute=0)  # Midnight daily
scheduler.run_async()  # Run in background
```

**Option B: Cron (Linux/Mac)**
```bash
crontab -e
# Add: 0 0 * * * cd /path/to/project && python -m scripts.backup.backup_scheduler
```

**Option C: Task Scheduler (Windows)**
- Create task that runs: `python scripts/backup/backup_scheduler.py`

## Weekly USB Rotation

### Hardware Setup
```
USB Drive A (1TB)
  ├─ Week 1-2: At home (active backup destination)
  ├─ Week 3-4: In cassaforte (cold storage)
  └─ Week 5+: Rotate back

USB Drive B (1TB)
  ├─ Week 1-2: In cassaforte (cold storage)
  ├─ Week 3-4: At home (active backup destination)
  └─ Week 5+: Rotate back
```

### Manual Rotation Process
```bash
# Every Sunday:
python -m scripts.backup.backup_manager rotate-to-usb /mnt/usb_active/

# Then physically swap USB drives
# USB from home → cassaforte
# USB from cassaforte → home
```

## Restore Operations

### List Available Backups
```bash
python scripts/backup/restore_manager.py list
```

### Restore Latest Backup
```bash
python scripts/backup/restore_manager.py restore latest
```

### Restore Specific Backup
```bash
python scripts/backup/restore_manager.py restore database_backup_20260322_120000.db
```

### Restore with Verification
```bash
python scripts/backup/restore_manager.py restore latest --verify
```

## Backup Schedule

- **Daily**: Automatic at midnight
- **Rotation**: Weekly (Sunday)
- **Retention**: Last 4 backups kept
- **Total**: ~200MB per month (4 backups × 50MB DB)

## Monitoring

Check backup status:
```bash
python scripts/backup/backup_manager.py status
```

View logs:
```bash
tail -f logs/backup.log
```

Email alerts (optional):
- Edit backup_config.json
- Enable email notifications
- Receive alerts on success/failure

## Disaster Recovery Plan

### Scenario 1: Hard Drive Crash (PC)
1. Replace hard drive
2. Restore from USB cassaforte
3. Resume operations

### Scenario 2: Corrupted Database
1. List backups: `restore_manager.py list`
2. Restore previous good backup
3. Verify integrity
4. Continue

### Scenario 3: Ransomware
1. Database encrypted
2. All backups still on USB (isolated)
3. Boot from USB/fresh install
4. Restore from backup
5. System recovered

## Tips & Best Practices

✅ Keep USB drives in different locations
✅ Test restore monthly
✅ Check logs weekly
✅ Rotate USB drives on schedule
✅ Monitor backup size growth
✅ Keep USB devices away from magnets/heat
✅ Use cryptography-enabled USB (optional)

## Email Alerts Setup (Gmail)

> ⚠️ **Security**: Never commit real passwords to source control.
> Add `scripts/backup/backup_config.json` to `.gitignore` once you fill in real credentials,
> or use the `BACKUP_EMAIL_PASSWORD` environment variable instead of the `password` field.

1. Enable 2FA in Gmail
2. Create App Password
3. Add to backup_config.json:
```json
"email": {
  "enabled": true,
  "from_address": "your-email@gmail.com",
  "password": "xxxx xxxx xxxx xxxx"
}
```

4. Test: `backup_scheduler.py test-email`

## Cost Breakdown

- 2x USB 1TB drives: €30-40
- Cassaforte: €20-50 (one-time)
- Monthly maintenance: €0
- **Total Year 1: ~€40-90**

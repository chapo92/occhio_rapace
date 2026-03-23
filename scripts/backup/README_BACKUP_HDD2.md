# Auto-Backup System - HDD2 Setup

## Overview
Automatic daily backups to separate HDD2 (D:/) for disaster recovery.

## Why HDD2?

### Hardware Protection
```
HDD1 (C:/)              HDD2 (D:/)
├─ Windows              ├─ Auto-backups
├─ Programs             ├─ Database copies
├─ Database (LIVE)      └─ Fresh every night
└─ Active use

If HDD1 crashes:
  ✅ HDD2 has fresh backup
  ✅ Restore in 5 minutes
  ✅ Max loss: last 24 hours
```

## Setup (First Time)

### 1. Verify HDD2 Exists
```
# Windows - open File Explorer
D:/ should exist and show your second hard drive
```

### 2. Create Directories on HDD2
```
mkdir D:\backups
mkdir D:\logs
```

### 3. Verify Configuration
Check `scripts/backup/backup_config.json`:
```json
{
  "backup_dir": "D:/backups/",
  "log_file": "D:/logs/backup.log"
}
```

### 4. Test Backup (Manual)
```bash
python -m scripts.backup.backup_manager
```

Expected output:
```
[2026-03-22T...] Backup created on HDD2: D:/backups/database_backup_20260322_120000.db
[2026-03-22T...] Backup integrity verified
```

### 5. Enable Auto-Backup

**Option A: Python (Recommended)**
Add to your main application:
```python
from scripts.backup.backup_scheduler import BackupScheduler

scheduler = BackupScheduler()
scheduler.schedule_daily_backup(hour=0, minute=0)  # Midnight daily
scheduler.run_async()  # Background thread
```

**Option B: Windows Task Scheduler**
1. Open Task Scheduler
2. Create Basic Task
3. Name: "Poker Database Backup"
4. Trigger: Daily @ 00:00 (midnight)
5. Action: Run program
   - Program: `python.exe`
   - Arguments: `-m scripts.backup.backup_scheduler`
   - Start in: `C:\path\to\project\`

**Option C: Windows Batch Script**
Create `backup.bat`:
```batch
@echo off
cd /d C:\path\to\project
python -m scripts.backup.backup_manager
```
Schedule with Task Scheduler to run daily.

## Daily Operations

### Automatic Backup
- Runs every night @ midnight
- Copies database HDD1 → HDD2
- Verifies integrity
- Keeps last 4 backups (~200 MB total)
- Logs all activity

### Monitor Backups
```bash
# Check backup status
python -m scripts.backup.backup_manager status
```

View logs:
```
# Windows
type D:\logs\backup.log
```

## Disaster Recovery

### Scenario 1: HDD1 Corrupted
```bash
# List available backups
python -m scripts.backup.restore_manager list

# Restore latest
python -m scripts.backup.restore_manager restore latest

# Or restore specific
python -m scripts.backup.restore_manager restore database_backup_20260321_000000.db
```

### Scenario 2: Ransomware/Virus
```
HDD1 encrypted → HDD2 NOT encrypted (separate disk)

Steps:
1. Disconnect HDD1 (prevent spread)
2. Boot from USB recovery
3. Restore database from HDD2
4. Continue operations
```

### Scenario 3: Accidental Delete
```bash
# Database deleted by accident?
# Restore from HDD2 backup made last night

python -m scripts.backup.restore_manager restore latest
```

## Backup Schedule

```
Time              Action
00:00 (Midnight)  Auto-backup runs
                  HDD1 → HDD2
                  Database copied
                  Integrity verified
                  Old backups cleaned

Storage on HDD2:
  Backup 1: Today - 1 day old
  Backup 2: Today - 2 days old
  Backup 3: Today - 3 days old
  Backup 4: Today - 4 days old

Total space: ~200 MB (4 x 50 MB DB)
```

## Features

- Automatic Daily Backup
- Separate Physical Disk (HDD2)
- Quick Restore with rollback
- Space Efficient (keep only 4 recent backups)
- Integrity Verified (SQLite header validated)
- Logged Activity (`D:/logs/backup.log`)

## Troubleshooting

### "ERROR: Backup directory not accessible"
- Check D:/ drive is connected
- Verify D:/backups/ exists
- Try: `mkdir D:\backups`

### "ERROR: Source database not found"
- Check `database/poker_data.db` exists
- Verify path in `backup_config.json`
- Database must be on HDD1 (C:/)

### Backup not running at midnight
- Check Task Scheduler is enabled
- Verify script path is correct
- Check logs: `type D:\logs\backup.log`

### Restore failed
- Verify backup file on HDD2
- Check HDD2 has free space
- Run manual test: `python -m scripts.backup.backup_manager`

## Best Practices

- Verify Setup Monthly: `python -m scripts.backup.restore_manager list`
- Test Restore Quarterly to verify it works
- Monitor HDD2 Health via Windows Device Manager
- Keep HDD2 Powered On during backup window

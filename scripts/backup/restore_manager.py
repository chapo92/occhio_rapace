"""
Restore backups from HDD2 with verification
"""

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


class RestoreManager:
    def __init__(self, config_path='scripts/backup/backup_config.json'):
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        self.backup_dir = Path(self.config['backup_dir'])
        self.source_db = Path(self.config['source_database'])
        self.log_file = Path(self.config['log_file'])

    def list_backups(self):
        """List all available backups on HDD2"""
        backups = sorted(self.backup_dir.glob('database_backup_*.db'))

        print(f"\nAvailable backups on HDD2 ({self.backup_dir}):")
        print("=" * 60)
        for i, backup in enumerate(backups):
            stat = backup.stat()
            size_mb = stat.st_size / (1024 * 1024)
            created = datetime.fromtimestamp(stat.st_ctime)
            print(f"  [{i}] {backup.name}")
            print(f"      Size: {size_mb:.1f} MB | Created: {created.isoformat()}")

        print("=" * 60)
        return backups

    def restore_backup(self, backup_name, verify=True):
        """Restore specific backup from HDD2"""
        backup_path = self.backup_dir / backup_name

        if not backup_path.exists():
            print(f"ERROR: Backup not found: {backup_path}")
            return False

        current_backup = None
        try:
            # Create pre-restore backup first (on HDD1)
            if self.source_db.exists():
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                current_backup = self.source_db.parent / f"pre_restore_backup_{timestamp}.db"
                shutil.copy2(self.source_db, current_backup)
                print(f"Current database backed up to: {current_backup}")

            # Restore from HDD2 backup
            shutil.copy2(backup_path, self.source_db)

            # Verify restored database
            if verify:
                if not self._verify_database(self.source_db):
                    print("ERROR: Restored database failed verification")
                    # Rollback if available
                    if current_backup and current_backup.exists():
                        shutil.copy2(current_backup, self.source_db)
                        print("Rolled back to previous state")
                    return False

            print(f"SUCCESS: Database restored from {backup_name}")
            self._log(f"Database restored from HDD2: {backup_name}")
            return True

        except Exception as e:
            print(f"ERROR: Restore failed: {str(e)}")
            return False

    def restore_latest(self, verify=True):
        """Restore most recent backup from HDD2"""
        backups = sorted(self.backup_dir.glob('database_backup_*.db'))

        if not backups:
            print("ERROR: No backups found on HDD2")
            return False

        latest = backups[-1]
        print(f"Restoring latest backup: {latest.name}")
        return self.restore_backup(latest.name, verify)

    def _verify_database(self, db_path):
        """Verify database integrity"""
        try:
            # Check SQLite header
            with open(db_path, 'rb') as f:
                header = f.read(16)
                if not header.startswith(b'SQLite format 3'):
                    return False

            # Try to open database
            conn = sqlite3.connect(db_path)
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            conn.close()

            return True

        except Exception:
            return False

    def _log(self, message):
        """Log message"""
        timestamp = datetime.now().isoformat()
        log_message = f"[{timestamp}] {message}"
        try:
            with open(self.log_file, 'a') as f:
                f.write(log_message + '\n')
        except Exception:
            pass

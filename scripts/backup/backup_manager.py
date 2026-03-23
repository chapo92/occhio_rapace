"""
Core backup management system - HDD2 optimized
"""

import os
import shutil
import hashlib
import json
from datetime import datetime
from pathlib import Path


class BackupManager:
    def __init__(self, config_path='scripts/backup/backup_config.json'):
        self.config = self._load_config(config_path)
        self.backup_dir = Path(self.config['backup_dir'])
        self.source_db = Path(self.config['source_database'])
        self.log_file = Path(self.config['log_file'])

        # Create directories if they don't exist
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_config(self, path):
        with open(path, 'r') as f:
            return json.load(f)

    def create_backup(self):
        """Create timestamped backup on HDD2"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"database_backup_{timestamp}.db"
        backup_path = self.backup_dir / backup_name

        try:
            # Verify source exists
            if not self.source_db.exists():
                self._log(f"ERROR: Source database not found: {self.source_db}")
                return False

            # Verify HDD2 is accessible
            if not self.backup_dir.exists():
                self._log(f"ERROR: Backup directory not accessible: {self.backup_dir}")
                return False

            # Copy database to HDD2
            shutil.copy2(self.source_db, backup_path)

            # Verify integrity
            if not self._verify_backup(backup_path):
                self._log(f"ERROR: Backup integrity check failed: {backup_path}")
                backup_path.unlink()  # Delete corrupted backup
                return False

            self._log(f"SUCCESS: Backup created on HDD2: {backup_path}")
            return True

        except Exception as e:
            self._log(f"ERROR: Failed to create backup: {str(e)}")
            return False

    def _verify_backup(self, backup_path):
        """Verify backup file integrity"""
        try:
            # Check file size
            if backup_path.stat().st_size == 0:
                return False

            # Check SQLite header
            with open(backup_path, 'rb') as f:
                header = f.read(16)
                return header.startswith(b'SQLite format 3')

        except Exception:
            return False

    def _get_checksum(self, filepath):
        """Calculate file checksum"""
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def cleanup_old_backups(self):
        """Keep only N most recent backups"""
        max_backups = self.config.get('max_backups', 4)
        backups = sorted(self.backup_dir.glob('database_backup_*.db'))

        if len(backups) > max_backups:
            for old_backup in backups[:-max_backups]:
                try:
                    old_backup.unlink()
                    self._log(f"Deleted old backup: {old_backup.name}")
                except Exception as e:
                    self._log(f"ERROR deleting backup: {str(e)}")

    def log(self, message):
        """Public logging interface"""
        self._log(message)

    def _log(self, message):
        """Log message with timestamp"""
        timestamp = datetime.now().isoformat()
        log_message = f"[{timestamp}] {message}"

        # Print to console
        print(log_message)

        # Append to log file on HDD2
        try:
            with open(self.log_file, 'a') as f:
                f.write(log_message + '\n')
        except Exception as e:
            print(f"WARNING: Could not write to log file: {str(e)}")

    def get_backup_status(self):
        """Get status of all backups"""
        backups = sorted(self.backup_dir.glob('database_backup_*.db'))

        status = {
            'total_backups': len(backups),
            'backup_location': str(self.backup_dir),
            'backups': []
        }

        for backup in backups:
            stat = backup.stat()
            status['backups'].append({
                'name': backup.name,
                'size_mb': stat.st_size / (1024 * 1024),
                'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                'checksum': self._get_checksum(backup)
            })

        return status

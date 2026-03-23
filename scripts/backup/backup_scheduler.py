"""
Scheduler for automated backups (cron wrapper) - HDD2 optimized
"""

import threading
import time

import schedule

from scripts.backup.backup_manager import BackupManager


class BackupScheduler:
    def __init__(self, config_path='scripts/backup/backup_config.json'):
        self.manager = BackupManager(config_path)
        self.config = self.manager.config
        self.logger = self.manager.log

    def schedule_daily_backup(self, hour=0, minute=0):
        """Schedule daily backup at specific time"""
        schedule_time = f"{hour:02d}:{minute:02d}"
        schedule.every().day.at(schedule_time).do(self._backup_job)
        self.logger(f"Scheduled daily backup at {schedule_time} -> HDD2 (D:/backups/)")

    def _backup_job(self):
        """Execute backup job"""
        self.logger("=== BACKUP JOB STARTED ===")

        # Create backup on HDD2
        self.manager.create_backup()

        # Cleanup old backups on HDD2
        self.manager.cleanup_old_backups()

        # Log status
        status = self.manager.get_backup_status()
        self.logger(f"Total backups on HDD2: {status['total_backups']}")

        self.logger("=== BACKUP JOB COMPLETED ===")

    def run(self):
        """Run scheduler (blocking)"""
        self.logger("Backup scheduler started - Destination: HDD2 (D:/)")
        while True:
            schedule.run_pending()
            time.sleep(60)

    def run_async(self):
        """Run scheduler in background thread"""
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        self.logger("Backup scheduler running in background")
        return thread

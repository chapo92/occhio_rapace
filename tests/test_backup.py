"""Unit tests for the Auto-Backup & Rotation System."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.backup.backup_manager import BackupManager
from scripts.backup.restore_manager import RestoreManager


def _make_sqlite_db(path):
    """Helper: create a minimal valid SQLite database at path."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()


def _make_config(tmp_dir, source_db_path=None):
    """Helper: write a temporary backup_config.json and return its path."""
    backup_dir = os.path.join(tmp_dir, 'backups')
    log_file = os.path.join(tmp_dir, 'logs', 'backup.log')
    os.makedirs(backup_dir, exist_ok=True)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    if source_db_path is None:
        source_db_path = os.path.join(tmp_dir, 'poker_data.db')

    config = {
        'source_database': source_db_path,
        'backup_dir': backup_dir,
        'log_file': log_file,
        'max_backups': 4,
        'send_email_alerts': False,
        'email': {
            'enabled': False,
            'smtp_server': 'smtp.gmail.com',
            'smtp_port': 587,
            'from_address': 'test@example.com',
            'to_address': 'test@example.com',
            'username': 'test@example.com',
            'password': 'test-password',
        },
    }

    config_path = os.path.join(tmp_dir, 'backup_config.json')
    with open(config_path, 'w') as f:
        json.dump(config, f)

    return config_path, backup_dir, log_file, source_db_path


class TestBackupManagerCreateBackup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config_path, self.backup_dir, self.log_file, self.source_db = _make_config(self.tmp)

    def _make_manager(self):
        return BackupManager(self.config_path)

    def test_create_backup_success(self):
        _make_sqlite_db(self.source_db)
        manager = self._make_manager()
        result = manager.create_backup()

        self.assertTrue(result)
        backups = list(Path(self.backup_dir).glob('database_backup_*.db'))
        self.assertEqual(len(backups), 1)

    def test_create_backup_missing_source(self):
        # source database does not exist
        manager = self._make_manager()
        result = manager.create_backup()

        self.assertFalse(result)

    def test_create_backup_creates_log(self):
        _make_sqlite_db(self.source_db)
        manager = self._make_manager()
        manager.create_backup()

        self.assertTrue(os.path.exists(self.log_file))
        with open(self.log_file) as f:
            content = f.read()
        self.assertIn('SUCCESS', content)

    def test_backup_file_name_format(self):
        _make_sqlite_db(self.source_db)
        manager = self._make_manager()
        manager.create_backup()

        backups = list(Path(self.backup_dir).glob('database_backup_*.db'))
        self.assertEqual(len(backups), 1)
        name = backups[0].name
        self.assertTrue(name.startswith('database_backup_'))
        self.assertTrue(name.endswith('.db'))


class TestBackupManagerVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config_path, self.backup_dir, self.log_file, self.source_db = _make_config(self.tmp)

    def test_verify_valid_sqlite(self):
        _make_sqlite_db(self.source_db)
        manager = BackupManager(self.config_path)
        self.assertTrue(manager._verify_backup(Path(self.source_db)))

    def test_verify_empty_file(self):
        open(self.source_db, 'w').close()
        manager = BackupManager(self.config_path)
        self.assertFalse(manager._verify_backup(Path(self.source_db)))

    def test_verify_invalid_file(self):
        with open(self.source_db, 'wb') as f:
            f.write(b'not a sqlite database')
        manager = BackupManager(self.config_path)
        self.assertFalse(manager._verify_backup(Path(self.source_db)))


class TestBackupManagerChecksum(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config_path, _, _, _ = _make_config(self.tmp)

    def test_checksum_consistent(self):
        test_file = os.path.join(self.tmp, 'test.db')
        with open(test_file, 'wb') as f:
            f.write(b'test data for checksum')

        manager = BackupManager(self.config_path)
        checksum1 = manager._get_checksum(test_file)
        checksum2 = manager._get_checksum(test_file)
        self.assertEqual(checksum1, checksum2)

    def test_checksum_different_for_different_files(self):
        file1 = os.path.join(self.tmp, 'file1.db')
        file2 = os.path.join(self.tmp, 'file2.db')
        with open(file1, 'wb') as f:
            f.write(b'content one')
        with open(file2, 'wb') as f:
            f.write(b'content two')

        manager = BackupManager(self.config_path)
        self.assertNotEqual(manager._get_checksum(file1), manager._get_checksum(file2))


class TestBackupManagerCleanup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config_path, self.backup_dir, _, self.source_db = _make_config(self.tmp)
        _make_sqlite_db(self.source_db)

    def test_cleanup_keeps_max_backups(self):
        manager = BackupManager(self.config_path)

        # Create 6 fake backup files
        for i in range(6):
            path = Path(self.backup_dir) / f"database_backup_2026010{i}_000000.db"
            _make_sqlite_db(str(path))

        manager.cleanup_old_backups()

        remaining = sorted(Path(self.backup_dir).glob('database_backup_*.db'))
        self.assertEqual(len(remaining), 4)

    def test_cleanup_no_action_when_under_max(self):
        manager = BackupManager(self.config_path)

        for i in range(3):
            path = Path(self.backup_dir) / f"database_backup_2026010{i}_000000.db"
            _make_sqlite_db(str(path))

        manager.cleanup_old_backups()

        remaining = list(Path(self.backup_dir).glob('database_backup_*.db'))
        self.assertEqual(len(remaining), 3)


class TestBackupManagerRotate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config_path, self.backup_dir, _, self.source_db = _make_config(self.tmp)
        _make_sqlite_db(self.source_db)
        self.external_drive = os.path.join(self.tmp, 'usb')
        os.makedirs(self.external_drive)

    def test_rotate_to_existing_drive(self):
        manager = BackupManager(self.config_path)
        manager.create_backup()

        result = manager.rotate_to_external_drive(self.external_drive)
        self.assertTrue(result)

        files = list(Path(self.external_drive).glob('database_backup_*.db'))
        self.assertEqual(len(files), 1)

    def test_rotate_to_missing_drive(self):
        manager = BackupManager(self.config_path)
        manager.create_backup()

        result = manager.rotate_to_external_drive('/nonexistent/path')
        self.assertFalse(result)

    def test_rotate_no_backups(self):
        manager = BackupManager(self.config_path)
        result = manager.rotate_to_external_drive(self.external_drive)
        self.assertFalse(result)


class TestBackupManagerStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config_path, self.backup_dir, _, self.source_db = _make_config(self.tmp)
        _make_sqlite_db(self.source_db)

    def test_get_backup_status_empty(self):
        manager = BackupManager(self.config_path)
        status = manager.get_backup_status()

        self.assertEqual(status['total_backups'], 0)
        self.assertEqual(status['backups'], [])

    def test_get_backup_status_with_backup(self):
        manager = BackupManager(self.config_path)
        manager.create_backup()

        status = manager.get_backup_status()
        self.assertEqual(status['total_backups'], 1)
        self.assertEqual(len(status['backups']), 1)

        info = status['backups'][0]
        self.assertIn('name', info)
        self.assertIn('size_mb', info)
        self.assertIn('created', info)
        self.assertIn('checksum', info)


class TestRestoreManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config_path, self.backup_dir, _, self.source_db = _make_config(self.tmp)
        _make_sqlite_db(self.source_db)

    def _put_backup(self, name='database_backup_20260101_000000.db'):
        path = Path(self.backup_dir) / name
        _make_sqlite_db(str(path))
        return path

    def test_list_backups_empty(self):
        manager = RestoreManager(self.config_path)
        backups = manager.list_backups()
        self.assertEqual(len(backups), 0)

    def test_list_backups_returns_sorted(self):
        self._put_backup('database_backup_20260101_000000.db')
        self._put_backup('database_backup_20260102_000000.db')
        manager = RestoreManager(self.config_path)
        backups = manager.list_backups()
        self.assertEqual(len(backups), 2)
        self.assertLess(str(backups[0]), str(backups[1]))

    def test_restore_backup_success(self):
        backup = self._put_backup()
        manager = RestoreManager(self.config_path)
        result = manager.restore_backup(backup.name, verify=True)
        self.assertTrue(result)

    def test_restore_backup_missing(self):
        manager = RestoreManager(self.config_path)
        result = manager.restore_backup('does_not_exist.db', verify=False)
        self.assertFalse(result)

    def test_restore_latest_success(self):
        self._put_backup('database_backup_20260101_000000.db')
        self._put_backup('database_backup_20260102_000000.db')
        manager = RestoreManager(self.config_path)
        result = manager.restore_latest(verify=True)
        self.assertTrue(result)

    def test_restore_latest_no_backups(self):
        manager = RestoreManager(self.config_path)
        result = manager.restore_latest()
        self.assertFalse(result)

    def test_verify_valid_database(self):
        manager = RestoreManager(self.config_path)
        self.assertTrue(manager._verify_database(Path(self.source_db)))

    def test_verify_invalid_database(self):
        bad_file = os.path.join(self.tmp, 'bad.db')
        with open(bad_file, 'wb') as f:
            f.write(b'not sqlite')
        manager = RestoreManager(self.config_path)
        self.assertFalse(manager._verify_database(Path(bad_file)))

    def test_restore_creates_pre_restore_backup(self):
        backup = self._put_backup()
        manager = RestoreManager(self.config_path)
        manager.restore_backup(backup.name, verify=False)

        pre_restore = list(Path(self.source_db).parent.glob('pre_restore_backup_*.db'))
        self.assertEqual(len(pre_restore), 1)


if __name__ == '__main__':
    unittest.main()

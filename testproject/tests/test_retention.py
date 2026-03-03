from pathlib import Path
import time
import os
from datetime import timedelta
from django.utils import timezone

import pytest
from unittest.mock import patch, MagicMock
from django_db_backups.services.retention import clean_database_records, enforce_local_retention_policy, enforce_retention_policy
from django_db_backups.models import BackupRecord, RestoreRecord



@pytest.mark.django_db
@patch('django_db_backups.services.retention.DropboxStorage')
def test_enforce_retention_policy_deletes_oldest(mock_storage_class, settings):
    # Use new setting name
    settings.CLOUD_DB_BACKUP = {"DROPBOX_RETENTION_MAX_COUNT": 2, "DROPBOX_ACCESS_TOKEN": "token"}
    mock_storage = MagicMock()
    mock_storage_class.return_value = mock_storage
    
    mock_storage.list_backups.return_value = [
        "backup_20230101.zip",
        "backup_20230104.zip",
        "backup_20230102.zip",
        "backup_20230103.zip",
    ]
    
    enforce_retention_policy()
    
    assert mock_storage.delete.call_count == 2
    mock_storage.delete.assert_any_call("backup_20230102.zip")
    mock_storage.delete.assert_any_call("backup_20230101.zip")
    
    
@patch('django_db_backups.services.retention.DropboxStorage')
def test_enforce_retention_policy_under_limit(mock_storage_class, settings):
    settings.CLOUD_DB_BACKUP = {"MAX_KEEP": 5, "DROPBOX_TOKEN": "token"}
    mock_storage = MagicMock()
    mock_storage_class.return_value = mock_storage
    
    mock_storage.list_backups.return_value = ["backup_1.zip", "backup_2.zip"]
    
    enforce_retention_policy()
    
    mock_storage.delete.assert_not_called()
    
    

@pytest.mark.django_db
def test_enforce_local_retention_policy(tmp_path, settings):
    # Use new setting names
    settings.CLOUD_DB_BACKUP = {
        "RETENTION_MAX_COUNT": 2, 
        "RETENTION_MAX_AGE_DAYS": 30,
        "BACKUP_DIR": tmp_path
    }
    
    for i in range(4):
        p = tmp_path / f"backup_{i}.zip"
        p.touch()
        os.utime(p, (time.time() + i*10, time.time() + i*10))
        
    enforce_local_retention_policy()
    
    remaining = list(tmp_path.glob("backup_*.zip"))
    assert len(remaining) == 2
    assert (tmp_path / "backup_3.zip").exists()
    assert (tmp_path / "backup_2.zip").exists()

    
@pytest.mark.django_db
def test_local_retention_by_age(tmp_path: Path, settings):
    """Ensures files older than RETENTION_MAX_AGE_DAYS are deleted, even if count is low."""
    settings.CLOUD_DB_BACKUP = {
        "BACKUP_DIR": tmp_path,
        "RETENTION_MAX_COUNT": 100,  # High count so it doesn't trigger
        "RETENTION_MAX_AGE_DAYS": 30, # Age limit
    }
    
    # File 1: 10 days old (Keep)
    file_keep = tmp_path / "backup_keep.zip"
    file_keep.touch()
    keep_time = time.time() - (10 * 86400)
    os.utime(file_keep, (keep_time, keep_time))
    
    # File 2: 40 days old (Delete)
    file_delete = tmp_path / "backup_delete.zip"
    file_delete.touch()
    delete_time = time.time() - (40 * 86400)
    os.utime(file_delete, (delete_time, delete_time))
    
    enforce_local_retention_policy()
    
    assert file_keep.exists() is True
    assert file_delete.exists() is False

@pytest.mark.django_db
def test_clean_database_records(settings):
    """Ensures old BackupRecord and RestoreRecord rows are purged."""
    settings.CLOUD_DB_BACKUP = {
        "OPERATION_STATUS_RETENTION_DAYS": 7,
    }
    
    now = timezone.now()
    old_date = now - timedelta(days=10)
    recent_date = now - timedelta(days=2)
    
    # Create recent records
    BackupRecord.objects.create(db_type="sqlite", status="success")
    RestoreRecord.objects.create(source="test", status="success")
    
    # Create old records (we use .update() because auto_now_add overrides creation time)
    old_b = BackupRecord.objects.create(db_type="sqlite", status="success")
    BackupRecord.objects.filter(pk=old_b.pk).update(created_at=old_date)
    
    old_r = RestoreRecord.objects.create(source="test", status="success")
    RestoreRecord.objects.filter(pk=old_r.pk).update(created_at=old_date)
    
    assert BackupRecord.objects.count() == 2
    assert RestoreRecord.objects.count() == 2
    
    # Run cleanup
    clean_database_records()
    
    # Only recent records should remain
    assert BackupRecord.objects.count() == 1
    assert RestoreRecord.objects.count() == 1
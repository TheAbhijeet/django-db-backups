import time
import logging
from pathlib import Path
from datetime import timedelta
from django.utils import timezone
from django_db_backups.conf import get_setting
from django_db_backups.services.dropbox_storage import DropboxStorage
from django_db_backups.models import BackupRecord, RestoreRecord

logger = logging.getLogger(__name__)

def clean_database_records():
    """Deletes old operation records from the database."""
    days = get_setting("OPERATION_STATUS_RETENTION_DAYS")
    cutoff = timezone.now() - timedelta(days=days)
    
    deleted_backups, _ = BackupRecord.objects.filter(created_at__lt=cutoff).delete()
    deleted_restores, _ = RestoreRecord.objects.filter(created_at__lt=cutoff).delete()
    
    if deleted_backups or deleted_restores:
        logger.info(f"Cleaned up {deleted_backups} old backup records and {deleted_restores} old restore records.")

def enforce_retention_policy():
    """Enforces remote Dropbox retention."""
    max_keep = get_setting("DROPBOX_RETENTION_MAX_COUNT")
    try:
        storage = DropboxStorage()
        backups = storage.list_backups()
        backups.sort(reverse=True) 
        
        if len(backups) > max_keep:
            to_delete = backups[max_keep:]
            for backup_file in to_delete:
                logger.info(f"Retention: Deleting old remote backup {backup_file}")
                # Dropbox path logic handles the folder prefix internally
                storage.delete(backup_file)
    except Exception as e:
        logger.warning(f"Failed to enforce remote retention policy: {e}")

def enforce_local_retention_policy():
    """Enforces local retention based on count AND age."""
    max_keep = get_setting("RETENTION_MAX_COUNT")
    max_age_days = get_setting("RETENTION_MAX_AGE_DAYS")
    backup_dir = get_setting("BACKUP_DIR")
    
    if not backup_dir.exists():
        return

    files = list(backup_dir.glob("backup_*.zip"))
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    
    current_time = time.time()
    max_age_seconds = max_age_days * 86400

    # 1. Delete by Count
    if len(files) > max_keep:
        for file_path in files[max_keep:]:
            logger.info(f"Retention (Count): Deleting {file_path.name}")
            file_path.unlink(missing_ok=True)
            files.remove(file_path)

    # 2. Delete by Age (for remaining files)
    for file_path in files:
        if (current_time - file_path.stat().st_mtime) > max_age_seconds:
            logger.info(f"Retention (Age): Deleting {file_path.name}")
            file_path.unlink(missing_ok=True)
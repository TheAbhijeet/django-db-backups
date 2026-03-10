import os
import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from django.conf import settings
from django_db_backups.models import MediaBackupRecord
from django_db_backups.conf import get_setting
from django_db_backups.utils import calculate_sha256

logger = logging.getLogger(__name__)

def perform_media_backup(local_only=False):
    logger.info("Starting media backup...")
    
    # Create the record IMMEDIATELY so we can track failures
    record = MediaBackupRecord.objects.create(storage_location="pending")
    zip_path = None
    
    try:
        if not hasattr(settings, 'MEDIA_ROOT') or not settings.MEDIA_ROOT:
            raise ValueError("MEDIA_ROOT is not defined in settings.py. Cannot backup media.")
            
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.exists():
            # If the folder doesn't exist, there's nothing to backup, but it's not strictly an error.
            # We'll create it so the zip doesn't fail, resulting in an empty backup.
            logger.warning(f"MEDIA_ROOT ({media_root}) does not exist. Creating empty directory.")
            media_root.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = get_setting("BACKUP_DIR")
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        zip_path = backup_dir / f"media_backup_{timestamp}.zip"
        
        # 1. Zip the Media Directory
        logger.info(f"Zipping media directory: {media_root}")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(media_root):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(media_root)
                    zipf.write(file_path, arcname)
                    
            # Add metadata for validation
            sha256 = calculate_sha256(zip_path)
            metadata = {
                "type": "media",
                "timestamp": timestamp,
                "sha256_hash": sha256,
                "version": "0.4.0"
            }
            zipf.writestr("__metadata.json", json.dumps(metadata))

        # 2. Storage Logic (Auto-Detect Dropbox)
        use_dropbox = False
        if not local_only:
            try:
                from django_db_backups.services.dropbox_storage import DropboxStorage
                storage = DropboxStorage() 
                use_dropbox = True
            except ValueError:
                pass

        if use_dropbox:
            try:
                logger.info("Uploading media to Dropbox...")
                remote_path = f"/{zip_path.name}"
                storage.upload(str(zip_path), remote_path)
                record.storage_location = f"dropbox:{remote_path}"
                zip_path.unlink(missing_ok=True)
            except Exception as e:
                logger.error(f"Cloud upload failed: {e}")
                record.error_message = f"Cloud upload failed: {e}. Saved locally instead."
                record.storage_location = f"local_fallback:{zip_path}"
        else:
            record.storage_location = f"local:{zip_path}"
            logger.info("Saved media backup to local storage.")

        record.size_bytes = zip_path.stat().st_size if zip_path and zip_path.exists() else 0
        record.status = 'success'
        record.save()
        return record

    except Exception as e:
        logger.exception("Media backup failed.")
        record.status = 'failed'
        record.error_message = str(e)
        record.save()
        if zip_path and zip_path.exists(): 
            zip_path.unlink(missing_ok=True)
        raise
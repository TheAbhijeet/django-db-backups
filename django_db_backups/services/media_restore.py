import io
import json
import logging
import shutil
import zipfile
import traceback
from pathlib import Path
from django.conf import settings
from django_db_backups.models import MediaRestoreRecord
from django_db_backups.services.lock import RestoreLock
from django_db_backups.services.media_backup import perform_media_backup

logger = logging.getLogger(__name__)

def validate_media_backup(zip_path: Path):
    if not zip_path.exists():
        raise FileNotFoundError("Media backup file not found.")
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        if "__metadata.json" not in zipf.namelist():
            raise ValueError("Invalid media backup: __metadata.json missing.")
        metadata = json.loads(zipf.read("__metadata.json").decode('utf-8'))
        if metadata.get("type") != "media":
            raise ValueError("This is not a media backup file.")
    return metadata

def _perform_media_restore_internal(zip_path_str: str, is_rollback: bool = False):
    zip_path = Path(zip_path_str)
    
    logger.info(f"Validating media backup: {zip_path.name}")
    validate_media_backup(zip_path)
    
    if not hasattr(settings, 'MEDIA_ROOT') or not settings.MEDIA_ROOT:
        raise ValueError("MEDIA_ROOT is not defined in settings.py.")
        
    media_root = Path(settings.MEDIA_ROOT)
    
    # Safety Check: Prevent wiping root directories (e.g., if MEDIA_ROOT is mistakenly set to '/')
    if len(media_root.parts) <= 1:
        raise ValueError(f"MEDIA_ROOT ({media_root}) is too shallow. Aborting to prevent OS wipe.")

    safety_record = None
    if not is_rollback:
        try:
            logger.warning("Creating pre-restore safety media backup...")
            safety_record = perform_media_backup(local_only=True)
            logger.info(f"Safety media backup created at {safety_record.storage_location}")
        except Exception as e:
            logger.exception("CRITICAL: Failed to create safety media backup. Restore aborted.")
            raise RuntimeError(f"Safety backup failed: {e}")

    try:
        logger.info(f"Wiping contents of MEDIA_ROOT: {media_root}")
        if media_root.exists():
            # ---  Delete contents, not the mount point ---
            for item in media_root.iterdir():
                try:
                    if item.is_file() or item.is_symlink():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                except Exception as del_err:
                    logger.warning(f"Could not delete {item}: {del_err}")
        else:
            media_root.mkdir(parents=True, exist_ok=True)


        logger.info("Extracting media files...")
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            for member in zipf.namelist():
                if member != "__metadata.json":
                    zipf.extract(member, path=str(media_root))
                    
        logger.info("Media restore completed successfully.")

    except Exception as e:
        if not is_rollback and safety_record:
            logger.exception("Media restore failed! Attempting rollback.")
            try:
                safety_path = safety_record.storage_location.split('local:')[1]
                # Trigger rollback
                _perform_media_restore_internal(safety_path, is_rollback=True)
                logger.info("Rollback successful. Original media restored.")
            except Exception as rollback_e:
                logger.critical(f"CRITICAL: ROLLBACK FAILED! Your MEDIA_ROOT may be empty or corrupted. Error: {rollback_e}")
        raise e
    finally:
        # Cleanup the safety backup if the main restore was successful
        if safety_record and not is_rollback:
            safety_path = Path(safety_record.storage_location.split('local:')[1])
            safety_path.unlink(missing_ok=True)

def perform_media_restore(zip_path_str: str, record_id: int = None):
    """Public wrapper handling logging and state."""
    if record_id:
        record = MediaRestoreRecord.objects.get(id=record_id)
    else:
        record = MediaRestoreRecord.objects.create(source=Path(zip_path_str).name, status='pending')
    
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    try:
        with RestoreLock():
            _perform_media_restore_internal(zip_path_str)
        record.status = 'success'
        record.error_message = None
    except Exception as e:
        record.status = 'failed'
        record.error_message = str(e)
        logger.error(traceback.format_exc())
    finally:
        record.logs = log_stream.getvalue()
        record.save()
        logger.removeHandler(handler)
        log_stream.close()
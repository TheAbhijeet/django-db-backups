import os
import json
import logging
import zipfile
import subprocess
from datetime import datetime
from pathlib import Path
from django.conf import settings
from django.db import connection
from django_db_backups.models import BackupRecord
from django_db_backups.services.dropbox_storage import DropboxStorage
from django_db_backups.services.retention import enforce_local_retention_policy, enforce_retention_policy, clean_database_records
from django_db_backups.conf import get_setting
from django_db_backups.utils import calculate_sha256
from django.db import connections

logger = logging.getLogger(__name__)



def perform_backup(local_only=False):
    logger.info("Starting database backup...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = get_setting("BACKUP_DIR")
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    db_aliases = get_setting("DATABASES")
    records = []

    for alias in db_aliases:
        conn = connections[alias]
        vendor = conn.vendor
        db_settings = settings.DATABASES[alias]
        db_name = str(db_settings['NAME'])
        
        record = BackupRecord.objects.create(db_type=vendor, storage_location="local")
        target_file = None
        zip_path = None
        
        try:
            if vendor == 'sqlite':
                target_file = backup_dir / f"backup_{alias}_{timestamp}.sql"
                
                # Use Django's connection to get the raw sqlite3 connection object
                # This avoids external processes and file locking issues.
                raw_connection = conn.connection 
                
                with target_file.open('w', encoding='utf-8') as f:
                    for line in raw_connection.iterdump():
                        f.write(f'{line}\n')
                logger.info(f"Successfully dumped SQLite DB using iterdump: {target_file.name}")
                
            elif vendor == 'postgresql':
                target_file = backup_dir / f"backup_{alias}_{timestamp}.dump"
                
                # ---  Handle List vs String for Docker Support ---
                dump_path = get_setting("PG_DUMP_PATH")
                
                # 1. Construct Base Command
                if isinstance(dump_path, list):
                    # It's a Docker command: ["docker", "exec", ...]
                    cmd = dump_path.copy()
                    # For Docker, pass password via env var inside the container command
                    if db_settings.get('PASSWORD'):
                        cmd.insert(2, "-e")
                        cmd.insert(3, f"PGPASSWORD={db_settings.get('PASSWORD')}")
                    # Use 'localhost' inside container, or configured host
                    host = 'localhost' 
                else:
                    # It's a local binary string: "pg_dump"
                    cmd = [dump_path]
                    host = db_settings.get('HOST', 'localhost')

                # 2. Add Arguments
                cmd.extend([
                    f'-F{get_setting("PG_DUMP_FORMAT")}', 
                    '-U', db_settings['USER'], 
                    '-h', host, 
                    db_name
                ])
                
                # 3. Prepare Environment (Only needed for local execution)
                env = os.environ.copy()
                if not isinstance(dump_path, list) and db_settings.get('PASSWORD'):
                    env['PGPASSWORD'] = db_settings['PASSWORD']

                with target_file.open('w') as f:
                    subprocess.run(cmd, stdout=f, env=env, check=True)
            else:
                raise NotImplementedError(f"Database vendor {vendor} is not supported.")

            # Create Zip
            zip_path = backup_dir / f"backup_{alias}_{timestamp}.zip"
            sha256 = calculate_sha256(target_file)
            
            metadata = {
                "db_type": vendor,
                "db_alias": alias,
                "timestamp": timestamp,
                "sha256_hash": sha256,
                "version": "0.3.0"
            }
            if vendor == 'postgresql':
                with conn.cursor() as cursor:
                    cursor.execute("SELECT version();")
                    metadata['pg_version'] = cursor.fetchone()[0]

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED if get_setting("SQLITE_COMPRESS") else zipfile.ZIP_STORED) as zipf:
                zipf.write(target_file, arcname=target_file.name)
                zipf.writestr("metadata.json", json.dumps(metadata))
                
            target_file.unlink(missing_ok=True)
            
            # Storage Logic (Dropbox)
            use_dropbox = False
            
            # 1. Check if we SHOULD try Dropbox (Not local-only)
            if not local_only:
                try:
                    # 2. Check if we CAN use Dropbox (Are credentials set?)
                    from django_db_backups.services.dropbox_storage import DropboxStorage
                    # This init will raise ValueError if keys are missing
                    storage = DropboxStorage() 
                    use_dropbox = True
                except ValueError:
                    # Credentials missing -> Fallback to local
                    use_dropbox = False

            if use_dropbox:
                try:
                    logger.info("Uploading to Dropbox...")
                    remote_path = f"/{zip_path.name}"
                    storage.upload(str(zip_path), remote_path)
                    
                    record.storage_location = f"dropbox:{remote_path}"
                    # Delete local file only after successful upload
                    zip_path.unlink(missing_ok=True)
                except Exception as e:
                    # Upload failed (Network error, etc) -> Fallback to local
                    logger.error(f"Cloud upload failed: {e}")
                    record.error_message = f"Cloud upload failed: {e}"
                    record.storage_location = f"local_fallback:{zip_path}"
                    # Do NOT delete zip_path here, so we keep the local backup
            else:
                record.storage_location = f"local:{zip_path}"
                logger.info("Saved to local storage.")


            record.size_bytes = zip_path.stat().st_size if zip_path.exists() else 0
            record.status = 'success'
            record.save()
            records.append(record)

        except Exception as e:
            record.status = 'failed'
            record.error_message = str(e)
            record.save()
            if target_file: target_file.unlink(missing_ok=True)
            if zip_path: zip_path.unlink(missing_ok=True)
            raise

    # Cleanup operations
    clean_database_records()
    enforce_local_retention_policy()
    # We re-check if Dropbox is usable for retention
    if not local_only:
        try:
            from django_db_backups.services.dropbox_storage import DropboxStorage
            DropboxStorage() # Check credentials
            enforce_retention_policy()
        except ValueError:
            pass # Dropbox not configured, skip remote retention


    return records[0] if records else None
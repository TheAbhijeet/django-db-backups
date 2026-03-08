import os
import io
import json
import logging
import shutil
import sqlite3
import zipfile
import subprocess
import traceback
from pathlib import Path
from django.conf import settings
from django.db import connection, connections
from django_db_backups.services.lock import RestoreLock
from django_db_backups.conf import get_setting
from django_db_backups.utils import calculate_sha256
from django_db_backups.services.backup import perform_backup
from django_db_backups.models import RestoreRecord

logger = logging.getLogger(__name__)

def terminate_postgres_connections(db_name: str):
    """Safely terminate all other connections."""
    logger.warning(f"Terminating all other connections to {db_name}...")
    kill_sql = """
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = %s AND pid <> pg_backend_pid();
    """
    with connection.cursor() as cursor:
        cursor.execute(kill_sql, [db_name])
        

def safe_extract(zipf: zipfile.ZipFile, target_dir: Path) -> Path:
    for member in zipf.namelist():
        member_path = target_dir / Path(member).name
        if member_path.resolve().parent != target_dir.resolve():
            raise ValueError("Unsafe zip path detected!")
    return Path(zipf.extract([n for n in zipf.namelist() if n != "metadata.json"][0], path=str(target_dir)))

def validate_backup(zip_path: Path):
    """Synchronous validation of backup file."""
    if not zip_path.exists():
        raise FileNotFoundError(f"Backup file not found: {zip_path}")

    logger.info(f"Opening backup file: {zip_path.name}") # Added Log

    with zipfile.ZipFile(zip_path, 'r') as zipf:
        if "metadata.json" not in zipf.namelist():
            raise ValueError("Invalid backup: metadata.json missing.")
        
        try:
            metadata = json.loads(zipf.read("metadata.json").decode('utf-8'))
        except json.JSONDecodeError:
            raise ValueError("Invalid backup: metadata.json is corrupted.")

        vendor = connection.vendor
        if metadata.get("db_type") != vendor:
            raise ValueError(f"Backup DB type ({metadata.get('db_type')}) does not match current DB ({vendor}).")

        if vendor == 'postgresql' and 'pg_version' in metadata:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version();")
                target_version_str = cursor.fetchone()[0]
            source_major = int(metadata['pg_version'].split(' ')[1].split('.')[0])
            target_major = int(target_version_str.split(' ')[1].split('.')[0])
            if target_major < source_major:
                raise ValueError(f"Target PG version ({target_major}) is older than source ({source_major}).")

        if 'sha256_hash' in metadata:
            logger.info("Validating checksum...")
            extract_dir = Path(get_setting("BACKUP_DIR"))
            extract_dir.mkdir(parents=True, exist_ok=True)
            extracted_path_str = safe_extract(zipf, extract_dir)
            extracted_path = Path(extracted_path_str)
            try:
                calculated_hash = calculate_sha256(extracted_path)
                if calculated_hash != metadata['sha256_hash']:
                    raise ValueError("Checksum mismatch! The file is corrupt.")
                logger.info("Checksum matches metadata.") # Added Log
            finally:
                extracted_path.unlink(missing_ok=True)
    return metadata


def _perform_restore_internal(zip_path_str: str, is_rollback: bool = False):
    zip_path = Path(zip_path_str)
    
    # Validation
    metadata = validate_backup(zip_path)

    with zipfile.ZipFile(zip_path, 'r') as zipf:
        dump_filename = [name for name in zipf.namelist() if name != "metadata.json"][0]
        extract_dir = Path(get_setting("BACKUP_DIR"))
        extract_dir.mkdir(parents=True, exist_ok=True)
        extracted_path_str = zipf.extract(dump_filename, path=str(extract_dir))
        extracted_path = Path(extracted_path_str)

    safety_backup_record = None
    if not is_rollback:
        try:
            logger.warning("Creating pre-restore safety backup...")
            safety_backup_record = perform_backup(local_only=True)
            logger.info(f"Safety backup created at {safety_backup_record.storage_location}")
        except Exception:
            logger.exception("CRITICAL: Failed to create safety backup. Restore aborted.")
            extracted_path.unlink(missing_ok=True)
            return

    try:
        alias = metadata.get("db_alias", "default")
        db_settings = settings.DATABASES[alias]
        db_name = str(db_settings['NAME'])
        
        from django.db import connections # Ensure this is imported at the top of your file
        conn = connections[alias]
        vendor = conn.vendor

        if vendor == 'postgresql':
            # 1. KILL CONNECTIONS (Critical for Postgres)
            terminate_postgres_connections(db_name)
        
        # 2. Close connection
        connections.close_all()
        logger.info("All database connections closed. Starting restore process...")


        if vendor == 'sqlite':
            # 1. Read the entire SQL script from the extracted file
            sql_script = extracted_path.read_text(encoding='utf-8')
            
            # 2. Create a new, temporary database file
            restored_db_path = Path(f"{db_name}.restored")
            restored_db_path.unlink(missing_ok=True)
            
            # 3. Connect to the new DB and execute the script
            new_conn = sqlite3.connect(restored_db_path)
            new_conn.executescript(sql_script)
            new_conn.close()
            
            # 4. Atomically replace the old DB file
            shutil.move(str(restored_db_path), db_name) 
            logger.info("SQLite database restored and replaced successfully.")
                
        elif vendor == 'postgresql':
            restore_path = get_setting("PG_RESTORE_PATH")
            use_docker = isinstance(restore_path, list)
            
            # 1. Construct Base Command
            if use_docker:
                cmd = restore_path.copy()
                if db_settings.get('PASSWORD'):
                     cmd.insert(2, "-e")
                     cmd.insert(3, f"PGPASSWORD={db_settings.get('PASSWORD')}")
                host = 'localhost'
            else:
                cmd = [restore_path]
                host = db_settings.get('HOST', 'localhost')

            # 2. Add Arguments
            cmd.extend([
                '--clean', '--if-exists', '--single-transaction', '--no-owner',
                '-U', db_settings['USER'], 
                '-h', host, 
                '-d', db_name, 
            ])

            # 3. Prepare Environment
            env = os.environ.copy()
            if not use_docker and db_settings.get('PASSWORD'):
                env['PGPASSWORD'] = db_settings['PASSWORD']

            # 4. Execute
            if use_docker:
                 # Stream file to Docker via STDIN
                 with extracted_path.open('rb') as f:
                     result = subprocess.run(cmd, stdin=f, capture_output=True, text=True)
            else:
                 # Local file path
                 cmd.append(str(extracted_path))
                 result = subprocess.run(cmd, env=env, capture_output=True, text=True)

            if result.returncode > 1:
                raise RuntimeError(f"pg_restore failed: {result.stderr}")
            elif result.returncode == 1:
                logger.warning(f"pg_restore finished with warnings:\n{result.stderr}")
        
        logger.info("Database restore completed successfully.")

    except Exception as e:
        if not is_rollback and safety_backup_record:
            logger.exception("Restore failed! Attempting to roll back.")
            try:
                safety_backup_path = Path(safety_backup_record.storage_location.split('local:')[1])
                _perform_restore_internal(str(safety_backup_path), is_rollback=True)
                logger.info("Rollback successful.")
            except Exception as rollback_e:
                logger.critical(f"CRITICAL: ROLLBACK FAILED! Error: {rollback_e}")
        raise e
    finally:
        extracted_path.unlink(missing_ok=True)
        if safety_backup_record and not is_rollback:
            safety_backup_path = Path(safety_backup_record.storage_location.split('local:')[1])
            safety_backup_path.unlink(missing_ok=True)

def perform_restore(zip_path_str: str, record_id=None):
    """
    Public wrapper. Handles Locking, Audit Logging, and Error Capture.
    """
    # 1. Setup Audit Record (Now using UUIDs)
    if record_id:
        record = RestoreRecord.objects.get(id=record_id)
    else:
        record = RestoreRecord.objects.create(
            source=str(Path(zip_path_str).name),
            status='pending'
        )

    # 2. Setup Log Capture
    log_capture_string = io.StringIO()
    handler = logging.StreamHandler(log_capture_string)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    try:
        with RestoreLock():
            _perform_restore_internal(zip_path_str)
        
        record.status = 'success'
        record.error_message = None
        logger.info("Restore Record marked as SUCCESS.")

    except Exception as e:
        record.status = 'failed'
        record.error_message = str(e)
        logger.error(f"Restore failed: {e}")
        logger.error(traceback.format_exc())
        raise e
    
    finally:
        # 3. CRITICAL POST-RESTORE STEP
        # The database was likely wiped and replaced. We must close the stale connection.
        connections.close_all()
        
        # 2. Re-establish the connection by simply using it.
        # connection.ensure_connection()

        
        record.logs = log_capture_string.getvalue()
        
        try:
            # This will now use the newly re-established connection
            if not RestoreRecord.objects.filter(id=record.id).exists():
                record.save(force_insert=True)
            else:
                record.save()
        except Exception as save_err:
            logger.error(f"Could not save audit log to DB: {save_err}")
        
        logger.removeHandler(handler)
        log_capture_string.close()

import pytest
import zipfile
import json
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock
from django_db_backups.services.restore import perform_restore
from django_db_backups.models import BackupRecord, RestoreRecord
from django.db import connections 
from django.db import connection



def create_fake_backup_zip(path: Path, db_type="sqlite", content=b"dummy", metadata_extra=None):
    with zipfile.ZipFile(path, 'w') as zipf:
        zipf.writestr("backup.sql", content)
        
        correct_hash = hashlib.sha256(content).hexdigest()
        
        metadata = {"db_type": db_type, "version": "0.3.0", "sha256_hash": correct_hash}
        if metadata_extra:
            metadata.update(metadata_extra)
        
        zipf.writestr("metadata.json", json.dumps(metadata))




@pytest.mark.django_db
def test_perform_restore_fails_on_checksum_mismatch(tmp_path, settings):
    settings.CLOUD_DB_BACKUP = {"BACKUP_DIR": tmp_path}
    vendor = connection.vendor
    
    zip_path = tmp_path / "audit_failure.zip"
    create_fake_backup_zip(
        zip_path, 
        db_type=vendor,
        content=b"content", 
        metadata_extra={"sha256_hash": "wrong_hash"}
    )
    
    with pytest.raises(ValueError, match="Checksum mismatch"):
        perform_restore(str(zip_path))


@pytest.mark.django_db
@patch('django_db_backups.services.restore.connection')
def test_perform_restore_fails_on_pg_version_mismatch(mock_connection, tmp_path: Path, settings):
    """Ensures restore aborts if target PG is older than source."""
    settings.CLOUD_DB_BACKUP = {"BACKUP_DIR": tmp_path}
    mock_connection.vendor = 'postgresql'
    
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ('PostgreSQL 13.8 on x86_64-pc-linux-gnu', )
    mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
    
    zip_path = tmp_path / "test_backup.zip"
    create_fake_backup_zip(zip_path, db_type="postgresql", metadata_extra={"pg_version": "PostgreSQL 15.1"})

    with pytest.raises(ValueError, match="Target PG version \\(13\\) is older than source \\(15\\)"):
        perform_restore(str(zip_path))

# --- Simple Validation Tests (Largely Unchanged) ---

@pytest.mark.django_db
def test_perform_restore_missing_file():
    with pytest.raises(FileNotFoundError):
        perform_restore("/non/existent/path.zip")

@pytest.mark.django_db
def test_perform_restore_missing_metadata(tmp_path: Path):
    zip_path = tmp_path / "test_backup.zip"
    # Create a zip without the metadata file
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr("backup.sql", b"content")
    
    with pytest.raises(ValueError, match="metadata.json missing"):
        perform_restore(str(zip_path))

@pytest.mark.django_db
def test_perform_restore_db_mismatch(tmp_path: Path):
    current_vendor = connection.vendor
    mismatch_vendor = 'postgresql' if current_vendor == 'sqlite' else 'sqlite'
    
    zip_path = tmp_path / "test_backup.zip"
    create_fake_backup_zip(zip_path, db_type=mismatch_vendor)
    
    with pytest.raises(ValueError, match="does not match current DB"):
        perform_restore(str(zip_path))
        
        


@pytest.mark.skipif(connection.vendor != 'sqlite', reason="Test is specific to SQLite's file-swap restore logic")
@pytest.mark.django_db
@patch('django_db_backups.services.restore.perform_backup')
@patch('django_db_backups.services.restore.subprocess.run')
def test_perform_restore_sqlite_orchestration(mock_subprocess, mock_perform_backup, tmp_path: Path, settings):
    """
    Tests SQLite restore specifically checking the 'restore-to-temp-file-then-move' logic.
    """
    # 1. Setup paths
    db_path = tmp_path / "db.sqlite3"
    settings.DATABASES['default']['NAME'] = str(db_path) 

    settings.CLOUD_DB_BACKUP = {"BACKUP_DIR": tmp_path}

    # Ensure the "original" DB exists
    db_path.write_text("original db content")

    # 2. Create Backup Zip
    dump_content = b"new sqlite content"
    correct_hash = hashlib.sha256(dump_content).hexdigest()
    zip_path = tmp_path / "test_backup.zip"
    create_fake_backup_zip(zip_path, db_type="sqlite", content=dump_content, metadata_extra={"sha256_hash": correct_hash})

    # 3. Setup Safety Backup Mock
    safety_zip_path = tmp_path / "safety.zip"
    def create_real_safety_backup(*args, **kwargs):
        create_fake_backup_zip(safety_zip_path, content=b"safety content")
        mock_record = MagicMock(spec=BackupRecord)
        mock_record.storage_location = f"local:{safety_zip_path}"
        return mock_record
    mock_perform_backup.side_effect = create_real_safety_backup

    # 4. CRITICAL: Mock subprocess to simulate sqlite3 creating the .restored file
    def sqlite_side_effect(cmd, **kwargs):
        # cmd looks like: ['sqlite3', '.../db.sqlite3.restored']
        target_file = Path(cmd[1]) 
        # Create the file so shutil.move can find it later
        target_file.write_text("restored by subprocess mock")
        return MagicMock(returncode=0)
    
    mock_subprocess.side_effect = sqlite_side_effect

    # 5. Run Restore
    perform_restore(str(zip_path))

    # 6. Assertions
    mock_perform_backup.assert_called_once_with(local_only=True)
    
    # Check that subprocess was called targeting the temporary file
    args, _ = mock_subprocess.call_args
    assert str(args[0][1]).endswith(".restored")
    
    # Verify shutil.move worked: The main DB file should now contain the content created by our mock
    assert db_path.read_text() == "restored by subprocess mock"
    
    # Cleanup verification
    assert not Path(f"{db_path}.restored").exists()
    assert not safety_zip_path.exists()



@pytest.mark.django_db(transaction=True)
@patch('django_db_backups.services.restore.perform_backup')
@patch('django_db_backups.services.restore.subprocess.run')
def test_perform_restore_creates_audit_record_success(mock_subprocess, mock_perform_backup, tmp_path, settings):
    """
    Happy Path: Restore succeeds, record is marked success, logs match.
    """
    # 1. Configure Settings
    vendor = connection.vendor
    
    db_path = tmp_path / f"db.{vendor}"

    db_path.write_text("original db content") 
    settings.DATABASES['default']['NAME'] = str(db_path) 

    settings.CLOUD_DB_BACKUP = {"BACKUP_DIR": tmp_path}
    
    # 2. Create Valid Backup
    dump_content = b"content"
    correct_hash = hashlib.sha256(dump_content).hexdigest()
    zip_path = tmp_path / "audit_success.zip"
    create_fake_backup_zip(zip_path, db_type=vendor, content=dump_content, metadata_extra={"sha256_hash": correct_hash})
    
    # 3. Mock Safety Backup
    safety_zip_path = tmp_path / "safety.zip"
    def create_real_safety_backup(*args, **kwargs):
        create_fake_backup_zip(safety_zip_path, content=b"safety content")
        mock_record = MagicMock(spec=BackupRecord)
        mock_record.storage_location = f"local:{safety_zip_path}"
        return mock_record
    mock_perform_backup.side_effect = create_real_safety_backup

    # 4. Mock Subprocess (Success)
    def sqlite_side_effect(cmd, **kwargs):
        Path(cmd[1]).write_text("restored by mock")
        return MagicMock(returncode=0)
    mock_subprocess.side_effect = sqlite_side_effect

    # 5. Run Restore
    perform_restore(str(zip_path))
    
    # 6. Verify Record
    record = RestoreRecord.objects.last()
    assert record.source == "audit_success.zip"
    assert record.status == "success"
    assert "Validating checksum..." in record.logs
    assert "Restore Record marked as SUCCESS" in record.logs


@pytest.mark.django_db(transaction=True)
@patch('django_db_backups.services.restore.perform_backup')
@patch('django_db_backups.services.restore.subprocess.run')
def test_perform_restore_creates_audit_record_failure(mock_subprocess, mock_perform_backup, tmp_path, settings):
    """
    Non-Happy Path: Validation fails, record is marked failed, logs contain error.
    """
    settings.CLOUD_DB_BACKUP = {"BACKUP_DIR": tmp_path}
    
    vendor = connection.vendor

    
    # 1. Create Invalid Backup (Bad Hash)
    zip_path = tmp_path / "audit_failure.zip"
    create_fake_backup_zip(
        zip_path, 
        db_type=vendor, # Use correct vendor
        content=b"content", 
        metadata_extra={"sha256_hash": "wrong_hash"}
    )

    
    # 2. Run Restore (Expect Exception)
    with pytest.raises(ValueError, match="Checksum mismatch"):
        perform_restore(str(zip_path))
        
    # 3. Verify Record
    record = RestoreRecord.objects.last()
    assert record.source == "audit_failure.zip"
    assert record.status == "failed"
    assert record.error_message == "Checksum mismatch! The file is corrupt."
    
    # 4. Verify Logs contain the error
    assert "Validating checksum..." in record.logs
    assert "Restore failed: Checksum mismatch" in record.logs
    




@pytest.mark.django_db
@patch('django_db_backups.services.restore.perform_backup')
@patch('django_db_backups.services.restore.subprocess')
@patch('django_db_backups.services.restore.connection')
@patch('django_db_backups.services.restore.get_setting') 
def test_perform_restore_postgres_orchestration(mock_get_setting, mock_connection, mock_subprocess_module, mock_perform_backup, tmp_path: Path, settings):
    
    # ... (Settings Mock same as before) ...
    def mock_get_setting_side_effect(key):
        if key == "BACKUP_DIR": return tmp_path
        if key == "PG_RESTORE_PATH": return "pg_restore"
        return None
    mock_get_setting.side_effect = mock_get_setting_side_effect

    # ... (Global Connection Mock same as before) ...
    mock_connection.vendor = 'postgresql'
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ('PostgreSQL 14.0', )
    mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

    # --- FIX: Mock the REAL connection object in the registry ---
    # We don't replace the registry, we just modify the object it holds.
    real_conn = connections['default']
    # We use a context manager to patch the vendor attribute safely
    with patch.object(real_conn, 'vendor', 'postgresql'):
        
        # ... (Rest of setup) ...
        settings.DATABASES['default'] = {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'my_pg_db',
            'USER': 'pg_user',
            'HOST': 'localhost'
        }

        # ... (File creation) ...
        dump_content = b"postgres binary dump"
        correct_hash = hashlib.sha256(dump_content).hexdigest()
        zip_path = tmp_path / "test_pg_backup.zip"
        create_fake_backup_zip(
            zip_path, 
            db_type="postgresql", 
            content=dump_content, 
            metadata_extra={"sha256_hash": correct_hash, "pg_version": "PostgreSQL 14.0", "db_alias": "default"}
        )

        # ... (Safety Backup Mock) ...
        safety_zip_path = tmp_path / "safety_pg.zip"
        def create_real_safety_backup(*args, **kwargs):
            # IMPORTANT: Safety backup must match the MOCKED vendor (postgresql)
            # otherwise rollback validation will fail if it runs
            create_fake_backup_zip(safety_zip_path, db_type="postgresql", content=b"safety content")
            mock_record = MagicMock(spec=BackupRecord)
            mock_record.storage_location = f"local:{safety_zip_path}"
            return mock_record
        mock_perform_backup.side_effect = create_real_safety_backup

        # ... (Subprocess Mock) ...
        mock_subprocess_module.run.return_value = MagicMock(returncode=0, stderr="")
        
        # Run Restore
        perform_restore(str(zip_path))

    # Assertions
    mock_perform_backup.assert_called_once_with(local_only=True)
    
    args, _ = mock_subprocess_module.run.call_args
    cmd = args[0]
    assert cmd[0] == 'pg_restore'
    assert '--single-transaction' in cmd
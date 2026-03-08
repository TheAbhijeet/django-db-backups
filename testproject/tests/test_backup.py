from django.db import connection
import pytest
import zipfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from django_db_backups.models import BackupRecord
from django_db_backups.services.backup import perform_backup



@pytest.mark.django_db
@patch('django_db_backups.services.backup.subprocess.run')
def test_perform_backup_local_storage(mock_subprocess, settings, tmp_path: Path):
    settings.CLOUD_DB_BACKUP = {
        "STORAGE": "local", 
        "BACKUP_DIR": tmp_path
    }
    
    def side_effect_run(*args, **kwargs):
        if 'stdout' in kwargs:
            kwargs['stdout'].write("fake sql dump")
        return MagicMock(returncode=0)
        
    mock_subprocess.side_effect = side_effect_run
    
    record = perform_backup()
    
    assert record.status == 'success'
    assert record.storage_location.startswith("local:")
    
    zip_path = Path(record.storage_location.split("local:")[1])
    assert zip_path.exists()
    
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        assert "metadata.json" in zipf.namelist()
        metadata = json.loads(zipf.read("metadata.json").decode('utf-8'))
        assert metadata["db_type"] == connection.vendor  



@pytest.mark.skipif(connection.vendor != 'postgresql', reason="Test requires PostgreSQL")
@pytest.mark.django_db
@patch('django_db_backups.services.backup.subprocess.run')
def test_perform_backup_cleans_up_on_failure(mock_subprocess, settings, tmp_path: Path):
    settings.CLOUD_DB_BACKUP = {"STORAGE": "local", "BACKUP_DIR": tmp_path}
    
    mock_subprocess.side_effect = Exception("Simulated subprocess crash")
    
    with pytest.raises(Exception, match="Simulated subprocess crash"):
        perform_backup()
        
    record = BackupRecord.objects.first()
    assert record is not None
    assert record.status == 'failed'
    assert record.error_message == "Simulated subprocess crash"
    
    # Ensure no partial files are left in the backup dir
    assert len(list(tmp_path.iterdir())) == 0
   
   
@pytest.mark.django_db
@patch('django_db_backups.services.backup.connection')
@patch('django_db_backups.services.backup.subprocess.run')
def test_perform_backup_postgresql_success(mock_subprocess, mock_connection, settings, tmp_path: Path):
    # Simulate Postgres
    mock_connection.vendor = 'postgresql'
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ('PostgreSQL 14.5', )
    mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

    settings.DATABASES['default'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'my_pg_db',
        'USER': 'pg_user',
        'PASSWORD': 'supersecretpassword',
        'HOST': '127.0.0.1',
    }
    settings.CLOUD_DB_BACKUP = {
        "STORAGE": "local", 
        "BACKUP_DIR": tmp_path,
        "DATABASES": ["default"],
        "PG_DUMP_PATH": "pg_dump",
        "PG_DUMP_FORMAT": "c"
    }
    
    mock_subprocess.return_value = MagicMock(returncode=0)
    
    # We must patch connections dictionary to return our mock connection
    with patch('django_db_backups.services.backup.connections', {'default': mock_connection}):
        record = perform_backup()
    
    assert record.status == 'success'
    assert record.db_type == 'postgresql'
    
    mock_subprocess.assert_called_once()
    call_args, call_kwargs = mock_subprocess.call_args
    
    cmd = call_args[0]
    assert cmd[0] == 'pg_dump'
    assert cmd[1] == '-Fc'
    assert cmd[2] == '-U'
    assert cmd[3] == 'pg_user'
    
@pytest.mark.skipif(connection.vendor != 'postgresql', reason="Test requires PostgreSQL")
@pytest.mark.django_db
@patch('django_db_backups.services.backup.subprocess.run')
@patch('django_db_backups.services.dropbox_storage.DropboxStorage') 
@patch('django_db_backups.services.backup.enforce_retention_policy')
def test_perform_backup_default_db_success(mock_enforce, mock_storage_class, mock_subprocess, settings, tmp_path: Path):
    settings.CLOUD_DB_BACKUP = {
        "STORAGE": "dropbox", 
        "BACKUP_DIR": tmp_path,
        "DROPBOX_ACCESS_TOKEN": "test_token", 
        "DATABASES": ["default"],
        "SQLITE_BINARY": "sqlite3"
    }
    
    mock_storage = MagicMock()
    mock_storage_class.return_value = mock_storage
    mock_subprocess.return_value = MagicMock(returncode=0)
    
    record = perform_backup()
    
    vendor = connection.vendor
    assert record.status == 'success'
    assert record.db_type == vendor
    assert record.storage_location.startswith("dropbox:/")
    
    mock_subprocess.assert_called_once()
    mock_storage.upload.assert_called_once()
    mock_enforce.assert_called_once()

@pytest.mark.django_db
@patch('django_db_backups.services.backup.subprocess.run')
@patch('django_db_backups.services.dropbox_storage.DropboxStorage') # FIX
@patch('django_db_backups.services.backup.enforce_retention_policy')
def test_perform_backup_sqlite_success(mock_enforce, mock_storage_class, mock_subprocess, settings, tmp_path: Path):
    settings.CLOUD_DB_BACKUP = {
        "STORAGE": "dropbox", 
        "BACKUP_DIR": tmp_path,
        "DROPBOX_ACCESS_TOKEN": "test_token", 
        "DATABASES": ["default"],
        "SQLITE_BINARY": "sqlite3"
    }
    
    mock_storage = MagicMock()
    mock_storage_class.return_value = mock_storage
    mock_subprocess.return_value = MagicMock(returncode=0)
    
    record = perform_backup()
    
    assert record.status == 'success'
    assert record.storage_location.startswith("dropbox:/")
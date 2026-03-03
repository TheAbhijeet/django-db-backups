import zipfile

from django.db import connection
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django_db_backups.models import BackupRecord
import json

@pytest.fixture
def admin_client(client):
    User.objects.create_superuser('admin', 'admin@example.com', 'password')
    client.login(username='admin', password='password')
    return client



@pytest.mark.django_db
@patch('django_db_backups.admin.threading.Thread')
def test_admin_upload_restore_post(mock_thread, admin_client, tmp_path):
    url = reverse('admin:upload_restore')
    
    vendor = connection.vendor
    
    valid_zip_path = tmp_path / f"db.{vendor}"
    with zipfile.ZipFile(valid_zip_path, 'w') as zipf:
        zipf.writestr("backup.sql", "dummy content")
        # Metadata must match the test database (sqlite)
        metadata = {"db_type": vendor, "version": "0.2.0"}
        zipf.writestr("metadata.json", json.dumps(metadata))
        
    with open(valid_zip_path, 'rb') as f:
        file_content = f.read()
        
    fake_file = SimpleUploadedFile("uploaded_backup.zip", file_content, content_type="application/zip")
    # ------------------------------------------
    
    response = admin_client.post(url, {'backup_zip': fake_file}, follow=True)
    
    # Assertions
    # 1. Thread SHOULD start now because validation passes
    mock_thread.assert_called_once()
    
    # 2. Check for success message
    messages = list(response.context['messages'])
    assert len(messages) > 0
    assert "Validation successful" in str(messages[0])

@pytest.mark.django_db
@patch('django_db_backups.admin.threading.Thread')
def test_admin_trigger_backup(mock_thread, admin_client):
    url = reverse('admin:trigger_backup')
    response = admin_client.get(url)
    
    assert response.status_code == 302
    mock_thread.assert_called_once()
    assert mock_thread.call_args[1]['daemon'] is True

@pytest.mark.django_db
def test_admin_download_local_backup(admin_client, tmp_path: Path):
    # Create a fake local backup file
    fake_zip = tmp_path / "fake_backup.zip"
    fake_zip.write_bytes(b"fake zip content")
    
    record = BackupRecord.objects.create(
        db_type="sqlite", 
        status="success", 
        storage_location=f"local:{fake_zip}"
    )
    
    url = reverse('admin:download_backup', args=[record.pk])
    response = admin_client.get(url)
    
    assert response.status_code == 200
    assert response['Content-Type'] == 'application/zip'
    assert response['Content-Disposition'] == f'attachment; filename="{fake_zip.name}"'
    assert b"fake zip content" in response.getvalue()

@pytest.mark.django_db
@patch('django_db_backups.admin.DropboxStorage')
def test_admin_download_dropbox_backup(mock_storage_class, admin_client, tmp_path: Path):
    mock_storage = MagicMock()
    mock_storage_class.return_value = mock_storage
    
    # Simulate dropbox download writing to the target file
    def fake_download(remote_path, local_path):
        Path(local_path).write_bytes(b"dropbox zip content")
        
    mock_storage.download.side_effect = fake_download
    
    record = BackupRecord.objects.create(
        db_type="sqlite", 
        status="success", 
        storage_location="dropbox:/remote_backup.zip"
    )
    
    url = reverse('admin:download_backup', args=[record.pk])
    response = admin_client.get(url)
    
    assert response.status_code == 200
    assert response['Content-Type'] == 'application/zip'
    assert b"dropbox zip content" in response.getvalue()
    mock_storage.download.assert_called_once()

@pytest.mark.django_db
@patch('django_db_backups.admin.threading.Thread')
def test_admin_restore_existing_backup(mock_thread, admin_client):
    record = BackupRecord.objects.create(
        db_type="sqlite", 
        status="success", 
        storage_location="local:/fake/path.zip"
    )
    
    url = reverse('admin:restore_backup', args=[record.pk])
    response = admin_client.get(url)
    
    assert response.status_code == 302
    mock_thread.assert_called_once()

@pytest.mark.django_db
def test_admin_upload_restore_get(admin_client):
    url = reverse('admin:upload_restore')
    response = admin_client.get(url)
    
    assert response.status_code == 200
    assert b"Critical Warning: Data Overwrite" in response.content
    # Check for the escaped version of "Validate & Restore"
    assert b"Select Backup File" in response.content


  
@pytest.mark.django_db
@patch('django_db_backups.admin.threading.Thread') # Mock thread to ensure it's NOT called
def test_admin_upload_restore_invalid_file_validation(mock_thread, admin_client, tmp_path):
    url = reverse('admin:upload_restore')
    
    # Create an INVALID zip file (missing metadata.json)
    invalid_zip = tmp_path / "bad_backup.zip"
    with zipfile.ZipFile(invalid_zip, 'w') as zipf:
        zipf.writestr("backup.sql", "some sql")
        # Deliberately omitting metadata.json
        
    with invalid_zip.open('rb') as f:
        fake_file = SimpleUploadedFile("bad_backup.zip", f.read(), content_type="application/zip")
        
    response = admin_client.post(url, {'backup_zip': fake_file}, follow=True)
    
    # 1. Check for Error Message
    messages = list(response.context['messages'])
    assert len(messages) > 0
    assert "Invalid backup: metadata.json missing" in str(messages[0])
    assert messages[0].level_tag == 'error'
    
    # 2. Check that we stayed on the upload page (didn't redirect to list)
    # Note: In Django Admin, staying on page usually means 200 OK re-render or redirect to self
    # Our code redirects to "." which is the same page.
    
    # 3. CRITICAL: Ensure background thread was NEVER started
    mock_thread.assert_not_called()
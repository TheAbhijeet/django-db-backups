import pytest
import zipfile
import json
from pathlib import Path
from unittest.mock import patch
from django_db_backups.services.media_backup import perform_media_backup
from django_db_backups.services.media_restore import perform_media_restore

@pytest.fixture
def media_setup(tmp_path, settings):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "test_image.jpg").write_text("fake image data")
    
    settings.MEDIA_ROOT = str(media_dir)
    settings.CLOUD_DB_BACKUP = {"BACKUP_DIR": tmp_path, "STORAGE": "local"}
    return media_dir

@pytest.mark.django_db
def test_media_backup_success(media_setup, tmp_path):
    record = perform_media_backup(local_only=True)
    
    assert record.status == 'success'
    zip_path = Path(record.storage_location.split('local:')[1])
    assert zip_path.exists()
    
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        assert "test_image.jpg" in zipf.namelist()
        assert "__metadata.json" in zipf.namelist()

@pytest.mark.django_db
@patch('django_db_backups.services.media_restore.perform_media_backup')
def test_media_restore_success(mock_backup, media_setup, tmp_path):
    # 1. Create a fake media backup zip
    zip_path = tmp_path / "media_backup.zip"
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        zipf.writestr("new_image.png", "new data")
        zipf.writestr("__metadata.json", json.dumps({"type": "media"}))
        
    # 2. Run restore
    perform_media_restore(str(zip_path))
    
    # 3. Verify old file is gone and new file is present
    assert not (media_setup / "test_image.jpg").exists()
    assert (media_setup / "new_image.png").exists()
    assert (media_setup / "new_image.png").read_text() == "new data"
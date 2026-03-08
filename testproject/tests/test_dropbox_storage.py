import io

import pytest
from unittest.mock import patch, MagicMock
from django_db_backups.services.dropbox_storage import DropboxStorage


@pytest.fixture
def dropbox_settings(settings):
    """Fixture to provide valid Dropbox settings for tests."""
    settings.DJANGO_DB_BACKUP = {
        "DROPBOX_REFRESH_TOKEN": "test_token",
        "DROPBOX_APP_KEY": "test_key",
        "DROPBOX_APP_SECRET": "test_secret",
        "DROPBOX_FOLDER": "/test_folder",
        "MAX_UPLOAD_SIZE": 5 * 1024 * 1024 * 1024,
    }
    return settings


@pytest.mark.django_db
def test_dropbox_storage_init_missing_config(settings):
    settings.DJANGO_DB_BACKUP = {}
    with pytest.raises(ValueError, match='Dropbox is not configured. Please set DROPBOX_APP_KEY, DROPBOX_APP_SECRET, and DROPBOX_REFRESH_TOKEN.'):
        DropboxStorage()


@pytest.mark.django_db
@patch("django_db_backups.services.dropbox_storage.dropbox.Dropbox")
def test_dropbox_storage_uses_refresh_token(mock_dropbox, settings):
    settings.DJANGO_DB_BACKUP = {
        "DROPBOX_APP_KEY": "key",
        "DROPBOX_APP_SECRET": "sec",
        "DROPBOX_REFRESH_TOKEN": "ref",
        "DROPBOX_FOLDER": "/test",
    }
    DropboxStorage()
    mock_dropbox.assert_called_once_with(
        app_key="key", app_secret="sec", oauth2_refresh_token="ref"
    )


@pytest.mark.django_db
@patch("django_db_backups.services.dropbox_storage.dropbox.Dropbox")
def test_dropbox_storage_uses_access_token(mock_dropbox, dropbox_settings):
    DropboxStorage()
    mock_dropbox.assert_called_once_with(
    app_key="test_key",
    app_secret="test_secret",
    oauth2_refresh_token="test_token",
)


@pytest.mark.django_db
@patch("django_db_backups.services.dropbox_storage.dropbox.Dropbox")
def test_dropbox_upload_success(mock_dropbox, tmp_path, dropbox_settings):
    mock_client = MagicMock()
    mock_dropbox.return_value = mock_client

    test_file = tmp_path / "test.txt"
    test_file.write_text("content")

    storage = DropboxStorage()
    storage.upload(str(test_file), "test.txt")

    # Verify folder prefix is added
    mock_client.files_upload.assert_called_once()
    args, _ = mock_client.files_upload.call_args
    assert args[1] == "/test_folder/test.txt"


@pytest.mark.django_db
@patch("django_db_backups.services.dropbox_storage.dropbox.Dropbox")
def test_dropbox_download_success(mock_dropbox, tmp_path, dropbox_settings):
    mock_client = MagicMock()
    mock_dropbox.return_value = mock_client

    storage = DropboxStorage()
    local_file = tmp_path / "down.zip"
    storage.download("remote.zip", str(local_file))

    mock_client.files_download_to_file.assert_called_once_with(
        str(local_file), "/test_folder/remote.zip"
    )


@pytest.mark.django_db
@patch("django_db_backups.services.dropbox_storage.dropbox.Dropbox")
def test_dropbox_list_backups(mock_dropbox, dropbox_settings):
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.entries = []
    mock_client.files_list_folder.return_value = mock_result
    mock_dropbox.return_value = mock_client

    storage = DropboxStorage()
    storage.list_backups()

    mock_client.files_list_folder.assert_called_once_with("/test_folder")


@pytest.mark.django_db
@patch("django_db_backups.services.dropbox_storage.dropbox.Dropbox")
def test_dropbox_delete_success(mock_dropbox, dropbox_settings):
    mock_client = MagicMock()
    mock_dropbox.return_value = mock_client

    storage = DropboxStorage()
    storage.delete("old_backup.zip")

    mock_client.files_delete_v2.assert_called_once_with("/test_folder/old_backup.zip")


@pytest.mark.django_db
@patch("django_db_backups.services.dropbox_storage.dropbox.Dropbox")
@patch("django_db_backups.services.dropbox_storage.os.path.getsize")
def test_dropbox_chunked_upload_for_large_files(
    mock_getsize, mock_dropbox, tmp_path, dropbox_settings
):
    file_size = 10 * 1024 * 1024
    mock_getsize.return_value = file_size

    mock_client = MagicMock()
    mock_session_start = MagicMock()
    mock_session_start.session_id = "test_session_123"
    mock_client.files_upload_session_start.return_value = mock_session_start
    mock_dropbox.return_value = mock_client

    test_file = tmp_path / "large_file.zip"
    test_file.touch()

    storage = DropboxStorage()

    fake_file_content = b"0" * file_size
    fake_file_stream = io.BytesIO(fake_file_content)

    mock_open = MagicMock()
    mock_open.return_value.__enter__.return_value = fake_file_stream

    with patch("builtins.open", mock_open):
        storage.upload(str(test_file), "large_file.zip")
    # ----------------------------------------------------------

    mock_client.files_upload.assert_not_called()
    mock_client.files_upload_session_start.assert_called_once()
    mock_client.files_upload_session_append_v2.assert_called_once()
    mock_client.files_upload_session_finish.assert_called_once()

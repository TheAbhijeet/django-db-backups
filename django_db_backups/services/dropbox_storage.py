import os
import logging
import dropbox
from django_db_backups.conf import get_setting

logger = logging.getLogger(__name__)

class DropboxStorage:
    def __init__(self):
        self.app_key = get_setting("DROPBOX_APP_KEY")
        self.app_secret = get_setting("DROPBOX_APP_SECRET")
        self.refresh_token = get_setting("DROPBOX_REFRESH_TOKEN")
        self.folder = get_setting("DROPBOX_FOLDER").rstrip('/')

        if not all([self.app_key, self.app_secret, self.refresh_token]):
            raise ValueError(
                "Dropbox is not configured. "
                "Please set DROPBOX_APP_KEY, DROPBOX_APP_SECRET, and DROPBOX_REFRESH_TOKEN."
            )

        self.client = dropbox.Dropbox(
            app_key=self.app_key,
            app_secret=self.app_secret,
            oauth2_refresh_token=self.refresh_token
        )

    def _get_full_path(self, path):
        path = path.lstrip('/')
        return f"{self.folder}/{path}"

    def upload(self, file_path, destination_path):
        remote_path = self._get_full_path(destination_path)
        file_size = os.path.getsize(file_path)
        chunk_size = 4 * 1024 * 1024 
        
        if file_size > get_setting("MAX_UPLOAD_SIZE"):
            raise ValueError(f"File exceeds MAX_UPLOAD_SIZE of {get_setting('MAX_UPLOAD_SIZE')} bytes.")

        with open(file_path, 'rb') as f:
            if file_size <= chunk_size:
                self.client.files_upload(f.read(), remote_path, mode=dropbox.files.WriteMode.overwrite)
            else:
                upload_session_start_result = self.client.files_upload_session_start(f.read(chunk_size))
                cursor = dropbox.files.UploadSessionCursor(session_id=upload_session_start_result.session_id, offset=f.tell())
                commit = dropbox.files.CommitInfo(path=remote_path, mode=dropbox.files.WriteMode.overwrite)
                while f.tell() < file_size:
                    if (file_size - f.tell()) <= chunk_size:
                        self.client.files_upload_session_finish(f.read(chunk_size), cursor, commit)
                    else:
                        self.client.files_upload_session_append_v2(f.read(chunk_size), cursor)
                        cursor.offset = f.tell()

    def download(self, remote_path, local_path):
        full_path = self._get_full_path(remote_path)
        self.client.files_download_to_file(str(local_path), full_path)

    def list_backups(self):
        try:
            result = self.client.files_list_folder(self.folder)
            return [entry.name for entry in result.entries if isinstance(entry, dropbox.files.FileMetadata)]
        except Exception:
            return []

    def delete(self, path):
        full_path = self._get_full_path(path)
        self.client.files_delete_v2(full_path)
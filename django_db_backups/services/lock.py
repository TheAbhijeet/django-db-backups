import time
import tempfile
from pathlib import Path
from django_db_backups.conf import get_setting

class RestoreLock:
    def __init__(self):
        self.lock_file = Path(tempfile.gettempdir()) / 'django_db_restore.lock'
        self.timeout = get_setting("LOCK_TIMEOUT_SECONDS")

    def __enter__(self):
        if self.lock_file.exists():
            mtime = self.lock_file.stat().st_mtime
            if (time.time() - mtime) > self.timeout:
                self.lock_file.unlink(missing_ok=True)
            else:
                raise RuntimeError("A restore operation is already in progress.")
        
        self.lock_file.write_text("LOCKED")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.lock_file.unlink(missing_ok=True)
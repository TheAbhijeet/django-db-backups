import os
from pathlib import Path
from typing import Any
from django.conf import settings

def get_default_backup_dir() -> Path:
    return Path(getattr(settings, 'BASE_DIR', Path('/tmp'))) / "django_db_backups"

DEFAULTS: dict[str, Any] = {
    "BACKUP_DIR": "",
    "DATABASES": ["default"],
    "PG_DUMP_FORMAT": "c",  # 'c' corresponds to custom format in pg_dump
    "PG_DUMP_PATH": "pg_dump",
    "PG_RESTORE_PATH": "pg_restore",
    "PSQL_PATH": "psql",
    "SQLITE_COMPRESS": True,
    "RETENTION_MAX_COUNT": 10,
    "RETENTION_MAX_AGE_DAYS": 30,
    
    "DROPBOX_REFRESH_TOKEN": "",
    "DROPBOX_APP_KEY": "",
    "DROPBOX_APP_SECRET": "",
    "DROPBOX_FOLDER": "/django-dbbackup",
    "DROPBOX_RETENTION_MAX_COUNT": 5,
    
    "LOCK_TIMEOUT_SECONDS": 1800,  # 30 minutes
    "MAX_UPLOAD_SIZE": 5 * 1024 * 1024 * 1024,  # 5GB
    "OPERATION_STATUS_RETENTION_DAYS": 7,
    "REQUIRE_SUPERUSER": True,
    "AUTO_BACKUP_INTERVAL_DAYS": 0,
}

def get_setting(key: str):
    user_config = getattr(settings, "CLOUD_DB_BACKUP", {})
    val = user_config.get(key, DEFAULTS.get(key))
    
    if key == "BACKUP_DIR" and not val:
        return get_default_backup_dir()

    if key == "DATABASES" and "DATABASES" not in user_config:
        return list(settings.DATABASES.keys())

    if key in ["PG_DUMP_PATH", "PG_RESTORE_PATH"] and get_setting("POSTGRES_CONTAINER_NAME"):
        container = get_setting("POSTGRES_CONTAINER_NAME")
        binary = "pg_dump" if key == "PG_DUMP_PATH" else "pg_restore"
        return ["docker", "exec", "-i", container, binary]
        
    return val
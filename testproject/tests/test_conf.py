import pytest
from pathlib import Path
from django_db_backups.conf import get_setting

def test_get_setting_default(settings):
    # Ensure no overrides
    settings.CLOUD_DB_BACKUP = {}
    assert get_setting("PG_DUMP_FORMAT") == "c"
    assert get_setting("RETENTION_MAX_COUNT") == 10
    assert get_setting("REQUIRE_SUPERUSER") is True

def test_get_setting_override(settings):
    settings.CLOUD_DB_BACKUP = {"PG_DUMP_FORMAT": "p"}
    assert get_setting("PG_DUMP_FORMAT") == "p"

def test_get_setting_backup_dir_default(settings):
    # Remove BACKUP_DIR from settings to test the fallback
    settings.CLOUD_DB_BACKUP = {}
    val = get_setting("BACKUP_DIR")
    assert isinstance(val, Path)
    assert val.name == "django_db_backups"
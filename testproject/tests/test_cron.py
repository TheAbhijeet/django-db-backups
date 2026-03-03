import pytest
from unittest.mock import patch, MagicMock
from django_db_backups.services.cron import CronManager, CRON_COMMENT

@patch('django_db_backups.services.cron.subprocess.run')
def test_update_cron_adds_job(mock_run, settings):
    settings.CLOUD_DB_BACKUP = {"AUTO_BACKUP_INTERVAL_DAYS": 7}
    
    # Mock reading existing crontab (empty)
    mock_run.return_value = MagicMock(returncode=0, stdout="")
    
    manager = CronManager()
    msg = manager.update_cron()
    
    assert "Successfully added" in msg
    
    # Verify write call
    # The second call to run should be the write ('crontab', '-')
    args, kwargs = mock_run.call_args
    assert args[0] == ['crontab', '-']
    assert CRON_COMMENT in kwargs['input']
    assert "dbbackup --auto" in kwargs['input']

@patch('django_db_backups.services.cron.subprocess.run')
def test_update_cron_removes_if_disabled(mock_run, settings):
    settings.CLOUD_DB_BACKUP = {"AUTO_BACKUP_INTERVAL_DAYS": 0}
    
    # Mock existing crontab with our job
    existing_cron = f"0 3 * * * python manage.py dbbackup {CRON_COMMENT}\n"
    mock_run.return_value = MagicMock(returncode=0, stdout=existing_cron)
    
    manager = CronManager()
    msg = manager.update_cron()
    
    assert "Removed" in msg
    
    # Verify write call has empty input (job removed)
    args, kwargs = mock_run.call_args
    assert args[0] == ['crontab', '-']
    assert CRON_COMMENT not in kwargs['input']
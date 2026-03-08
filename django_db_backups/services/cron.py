import os
import sys
import subprocess
from django.conf import settings
from django_db_backups.conf import get_setting

CRON_COMMENT = "# django-db-backups-backup-job"

class CronManager:
    def __init__(self):
        self.python_path = sys.executable
        self.manage_py = self._find_manage_py()
        
    def _find_manage_py(self):
        # Heuristic to find manage.py relative to settings
        base_dir = getattr(settings, 'BASE_DIR', None)
        if base_dir:
            manage = os.path.join(base_dir, 'manage.py')
            if os.path.exists(manage):
                return manage
        # Fallback: Assume we are running from the project root
        return "manage.py"

    def _get_current_crontab(self):
        try:
            # List current crontab
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            if result.returncode != 0:
                return [] # No crontab exists yet
            return result.stdout.strip().split('\n')
        except FileNotFoundError:
            raise RuntimeError("crontab command not found. This feature requires Linux/MacOS.")

    def _write_crontab(self, lines):
        cron_content = '\n'.join(lines) + '\n'
        subprocess.run(['crontab', '-'], input=cron_content, text=True, check=True)

    def update_cron(self):
        interval_days = get_setting("AUTO_BACKUP_INTERVAL_DAYS")
        
        if interval_days <= 0:
            self.remove_cron()
            return "Auto-backup disabled. Removed cron job."

        # Construct the command
        # 0 3 * * * /path/to/python /path/to/manage.py dbbackup --auto
        cmd = f"0 3 * * * {self.python_path} {self.manage_py} dbbackup --auto {CRON_COMMENT}"
        
        current_lines = self._get_current_crontab()
        new_lines = [line for line in current_lines if CRON_COMMENT not in line]
        
        new_lines.append(cmd)
        self._write_crontab(new_lines)
        
        return f"Successfully added cron job: Run daily at 3:00 AM (checks every {interval_days} days)."

    def remove_cron(self):
        current_lines = self._get_current_crontab()
        new_lines = [line for line in current_lines if CRON_COMMENT not in line]
        
        if len(new_lines) < len(current_lines):
            self._write_crontab(new_lines)
            return "Removed existing backup cron job."
        return "No existing backup cron job found."
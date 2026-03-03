from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django_db_backups.services.backup import perform_backup
from django_db_backups.models import BackupRecord
from django_db_backups.conf import get_setting

class Command(BaseCommand):
    help = 'Creates a database backup.'

    def add_arguments(self, parser):
        parser.add_argument('--local', action='store_true', help='Force local backup')
        parser.add_argument('--auto', action='store_true', help='Run only if the interval has passed')

    def handle(self, *args, **options):
        local_only = options['local']
        auto_mode = options['auto']

        if auto_mode:
            interval_days = get_setting("AUTO_BACKUP_INTERVAL_DAYS")
            if interval_days <= 0:
                self.stdout.write("Auto-backup disabled in settings. Exiting.")
                return

            # Check the last successful backup
            last_backup = BackupRecord.objects.filter(status='success').order_by('-created_at').first()
            
            if last_backup:
                time_since_last = timezone.now() - last_backup.created_at
                if time_since_last < timedelta(days=interval_days):
                    self.stdout.write(f"Skipping: Last backup was {time_since_last.days} days ago. Interval is {interval_days} days.")
                    return

        self.stdout.write("Starting database backup...")
        try:
            perform_backup(local_only=local_only)
            self.stdout.write(self.style.SUCCESS("Backup completed successfully."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Backup failed: {str(e)}"))
import os

from django.core.management.base import BaseCommand
from django_db_backups.services.cron import CronManager

class Command(BaseCommand):
    help = 'Updates the OS crontab based on settings.AUTO_BACKUP_INTERVAL_DAYS'

    def add_arguments(self, parser):
        parser.add_argument('--remove', action='store_true', help='Remove the cron job')

    def handle(self, *args, **options):
        if os.name == 'nt':
            self.stderr.write(self.style.ERROR("Automated cron management is not supported on Windows."))
            return

        manager = CronManager()
        
        try:
            if options['remove']:
                msg = manager.remove_cron()
            else:
                msg = manager.update_cron()
            
            self.stdout.write(self.style.SUCCESS(msg))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to update crontab: {str(e)}"))
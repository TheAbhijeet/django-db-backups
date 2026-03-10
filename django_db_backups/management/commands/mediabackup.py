from django.core.management.base import BaseCommand
from django_db_backups.services.media_backup import perform_media_backup

class Command(BaseCommand):
    help = 'Creates a backup of the MEDIA_ROOT directory.'

    def add_arguments(self, parser):
        parser.add_argument('--local', action='store_true', help='Force local backup only')

    def handle(self, *args, **options):
        self.stdout.write("Starting media backup...")
        try:
            perform_media_backup(local_only=options['local'])
            self.stdout.write(self.style.SUCCESS("Media backup completed successfully."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Media backup failed: {str(e)}"))
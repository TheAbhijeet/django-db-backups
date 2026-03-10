from django.core.management.base import BaseCommand
from django_db_backups.services.media_restore import perform_media_restore

class Command(BaseCommand):
    help = 'Restores the MEDIA_ROOT directory from a zip file.'

    def add_arguments(self, parser):
        parser.add_argument('backup_file', type=str, help='Path to the media backup .zip file')

    def handle(self, *args, **options):
        backup_file = options['backup_file']
        self.stdout.write(self.style.WARNING("WARNING: This will WIPE and replace your current MEDIA_ROOT."))
        confirm = input("Are you sure you want to continue? (yes/no): ")
        
        if confirm.lower() != 'yes':
            self.stdout.write(self.style.ERROR("Restore cancelled."))
            return

        self.stdout.write("Starting media restore...")
        try:
            perform_media_restore(backup_file)
            self.stdout.write(self.style.SUCCESS("Media restored successfully."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Media restore failed: {str(e)}"))
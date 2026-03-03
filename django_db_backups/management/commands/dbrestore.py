from django.core.management.base import BaseCommand
from django_db_backups.services.restore import perform_restore

class Command(BaseCommand):
    help = 'Restores the database from a local zip backup file.'

    def add_arguments(self, parser):
        parser.add_argument('backup_file', type=str, help='Path to the backup .zip file')

    def handle(self, *args, **options):
        backup_file = options['backup_file']
        self.stdout.write(self.style.WARNING("WARNING: This will overwrite your current database and log out all users."))
        confirm = input("Are you sure you want to continue? (yes/no): ")
        
        if confirm.lower() != 'yes':
            self.stdout.write(self.style.ERROR("Restore cancelled."))
            return

        self.stdout.write("Starting database restore...")
        try:
            perform_restore(backup_file)
            self.stdout.write(self.style.SUCCESS("Database restored successfully."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Restore failed: {str(e)}"))
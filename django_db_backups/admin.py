import logging
import threading
import tempfile
from pathlib import Path
import traceback
from django.contrib import admin
from django.contrib import messages
from django.http import HttpResponseRedirect, FileResponse, Http404
from django.urls import path, reverse
from django.shortcuts import render
from django.utils.html import format_html
from django_db_backups.conf import get_setting
from django_db_backups.models import BackupRecord, MediaBackupRecord, MediaRestoreRecord, RestoreRecord
from django_db_backups.services.backup import perform_backup
from django_db_backups.services.media_backup import perform_media_backup
from django_db_backups.services.media_restore import perform_media_restore, validate_media_backup
from django_db_backups.services.restore import perform_restore, validate_backup
from django_db_backups.services.dropbox_storage import DropboxStorage
from django.core.exceptions import PermissionDenied

logger = logging.getLogger(__name__)



@admin.register(RestoreRecord)
class RestoreRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'source', 'status')
    readonly_fields = ('id', 'created_at', 'source', 'status', 'error_message', 'logs')
    list_filter = ('status', 'created_at')

    def has_add_permission(self, request):
        return False # Restores are created by the system, not manually added here

@admin.register(BackupRecord)
class BackupRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'db_type', 'created_at', 'status', 'storage_location', 'size_bytes', 'admin_actions')
    readonly_fields = ('id', 'db_type', 'created_at', 'status', 'storage_location', 'size_bytes', 'error_message')
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('trigger-backup/', self.admin_site.admin_view(self.trigger_backup), name='trigger_backup'),
            path('<path:object_id>/download/', self.admin_site.admin_view(self.download_backup), name='download_backup'),
            path('<path:object_id>/restore/', self.admin_site.admin_view(self.restore_backup), name='restore_backup'),
            path('upload-restore/', self.admin_site.admin_view(self.upload_restore), name='upload_restore'), 
            path('test-dropbox/', self.admin_site.admin_view(self.test_dropbox), name='test_dropbox'),

        ]
        return custom_urls + urls
    
    def has_module_permission(self, request):
        if get_setting("REQUIRE_SUPERUSER") and not request.user.is_superuser:
            return False
        return super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        if get_setting("REQUIRE_SUPERUSER") and not request.user.is_superuser:
            return False
        return super().has_view_permission(request, obj)


    def admin_actions(self, obj):
        if obj.status != 'success':
            return "-"
        return format_html(
            '<a class="button" href="{}">Download</a>&nbsp;'
            '<a class="button" style="background-color: #ba2121; color: white;" href="{}" '
            'onclick="return confirm(\'⚠️ WARNING: All users will be logged out and current DB overwritten. Continue?\');">Restore</a>',
            f"{obj.pk}/download/",
            f"{obj.pk}/restore/"
        )
    admin_actions.short_description = 'Actions'
    
    def has_add_permission(self, request):
        return False

    def trigger_backup(self, request):
        if get_setting("REQUIRE_SUPERUSER") and not request.user.is_superuser:
            raise PermissionDenied("Only superusers can trigger backups.")
        
        is_local = request.GET.get('local') == '1'

        def run_backup():
            try:
                perform_backup(local_only=is_local)
            except Exception:
                tb = traceback.format_exc()
                logger.critical(f"Background backup failed:\n{tb}")
                # mail_admins("CRITICAL: Django DB Backup Failed", f"A backup triggered from the admin panel has failed.\n\n{tb}")

        threading.Thread(target=run_backup, daemon=True).start()
        self.message_user(request, "Backup triggered in the background. Check logs for progress.", level=messages.INFO)
        return HttpResponseRedirect("../")
    
    def test_dropbox(self, request):
        if get_setting("REQUIRE_SUPERUSER") and not request.user.is_superuser:
            raise PermissionDenied("Only superusers can test connections.")
            
        try:
            storage = DropboxStorage()
            # Attempt to list files to prove we have read/write access
            storage.list_backups()
            self.message_user(request, "Dropbox connection successful! Credentials are valid.", level=messages.SUCCESS)
        except ValueError as e:
            self.message_user(request, f"Configuration Error: {str(e)}", level=messages.WARNING)
        except Exception as e:
            self.message_user(request, f"Connection Failed: {str(e)}", level=messages.ERROR)
            
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '../'))

    def download_backup(self, request, object_id):
        if get_setting("REQUIRE_SUPERUSER") and not request.user.is_superuser:
            raise PermissionDenied("Only superusers can trigger backups.")

        obj = self.get_object(request, object_id)
        if not obj or obj.status != 'success':
            raise Http404("Backup not found or not successful.")
        
        try:
            if obj.storage_location.startswith('local:'):
                file_path = Path(obj.storage_location.split('local:')[1])
                if not file_path.exists():
                    raise FileNotFoundError("Local backup file missing.")
                # ADDED content_type='application/zip'
                return FileResponse(file_path.open('rb'), as_attachment=True, filename=file_path.name, content_type='application/zip')
                
            elif obj.storage_location.startswith('dropbox:'):
                remote_path = obj.storage_location.split('dropbox:')[1]
                storage = DropboxStorage()
                temp_file = Path(tempfile.gettempdir()) / Path(remote_path).name
                storage.download(remote_path, str(temp_file))
                # ADDED content_type='application/zip'
                return FileResponse(temp_file.open('rb'), as_attachment=True, filename=temp_file.name, content_type='application/zip')
        except Exception as e:
            self.message_user(request, f"Download failed: {str(e)}", level=messages.ERROR)
            return HttpResponseRedirect("../../")
        
    def restore_backup(self, request, object_id):
        if get_setting("REQUIRE_SUPERUSER") and not request.user.is_superuser:
            raise PermissionDenied("Only superusers can trigger backups.")

        obj = self.get_object(request, object_id)
        if not obj or obj.status != 'success':
            raise Http404("Backup not found.")
        
                # 1. Create the record immediately
        restore_record = RestoreRecord.objects.create(
            source=f"Backup ID {obj.id} ({obj.db_type})",
            status='pending'
        )


        def run_restore():
            file_path_to_restore = None
            temp_file = None
            try:
                if obj.storage_location.startswith('local:'):
                    file_path_to_restore = obj.storage_location.split('local:')[1]
                elif obj.storage_location.startswith('dropbox:'):
                    remote_path = obj.storage_location.split('dropbox:')[1]
                    storage = DropboxStorage()
                    temp_file = Path(tempfile.gettempdir()) / Path(remote_path).name
                    storage.download(remote_path, str(temp_file))
                    file_path_to_restore = str(temp_file)
                
                if file_path_to_restore:
                    perform_restore(file_path_to_restore)
            except Exception as e:
                tb = traceback.format_exc()
                logger.critical(f"Background restore failed:\n{tb}")
                restore_record.status = 'failed'
                restore_record.error_message = str(e)
                restore_record.save()
                # mail_admins("CRITICAL: Django DB Restore Failed", f"A restore triggered from the admin panel has failed.\n\n{tb}")
            finally:
                if temp_file:
                    temp_file.unlink(missing_ok=True)

        threading.Thread(target=run_restore, daemon=True).start()
        self.message_user(request, "Restore triggered in the background. Check logs for progress. Users will be logged out shortly.", level=messages.WARNING)
        return HttpResponseRedirect("../../")

    def upload_restore(self, request):
        if get_setting("REQUIRE_SUPERUSER") and not request.user.is_superuser:
            raise PermissionDenied("Only superusers can trigger backups.")

        if request.method == 'POST' and request.FILES.get('backup_zip'):
            uploaded_file = request.FILES['backup_zip']
            
            # 1. Create Record
            restore_record = RestoreRecord.objects.create(
                source=f"Uploaded: {uploaded_file.name}",
                status='pending'
            )

            
            # 1. Save uploaded file to a temporary location
            temp_file = Path(tempfile.gettempdir()) / uploaded_file.name
            try:
                with temp_file.open('wb+') as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)
                
                # 2. SYNCHRONOUS VALIDATION
                # This runs immediately. If it fails, it raises an exception.
                validate_backup(temp_file)
                
            except Exception as e:
                # If validation fails, delete the file, show error, and STOP.
                temp_file.unlink(missing_ok=True)
                self.message_user(request, f"Error: {str(e)}", level=messages.ERROR)
                restore_record.status = 'failed'
                restore_record.error_message = str(e)
                restore_record.save()

                return HttpResponseRedirect(".") # Stay on the page
            
            # 3. If Valid, Start Background Thread
            def run_uploaded_restore():
                try:
                    perform_restore(str(temp_file))
                except Exception:
                    tb = traceback.format_exc()
                    logger.critical(f"Background restore from upload failed:\n{tb}")
                    # mail_admins("CRITICAL: Django DB Restore Failed", f"Restore failed.\n\n{tb}")
                finally:
                    temp_file.unlink(missing_ok=True)

            threading.Thread(target=run_uploaded_restore, daemon=True).start()
            self.message_user(request, "Validation successful. Restore started in background.", level=messages.WARNING)
            return HttpResponseRedirect("../")

        context = dict(self.admin_site.each_context(request))
        return render(request, 'admin/django_db_backups/backuprecord/upload_restore.html', context)



@admin.register(MediaBackupRecord)
class MediaBackupRecordAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'status', 'storage_location', 'size_bytes', 'admin_actions')
    readonly_fields = ('created_at', 'status', 'storage_location', 'size_bytes', 'error_message')
    
    def has_add_permission(self, request): return False
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('trigger-media-backup/', self.admin_site.admin_view(self.trigger_media_backup), name='trigger_media_backup'),
            path('<path:object_id>/download-media/', self.admin_site.admin_view(self.download_media), name='download_media'),
            path('<path:object_id>/restore-media/', self.admin_site.admin_view(self.restore_media), name='restore_media'),
            path('upload-restore-media/', self.admin_site.admin_view(self.upload_restore_media), name='upload_restore_media'),
        ]
        return custom_urls + urls

    def admin_actions(self, obj):
        if obj.status != 'success': return "-"
        return format_html(
            '<a class="button" href="{}">Download</a>&nbsp;'
            '<a class="button" style="background-color: #ba2121; color: white;" href="{}" '
            'onclick="return confirm(\'⚠️ WARNING: Current media will be wiped and replaced. Continue?\');">Restore</a>',
            f"{obj.pk}/download-media/",
            f"{obj.pk}/restore-media/"
        )
    admin_actions.short_description = 'Actions'

    def trigger_media_backup(self, request):
        is_local = request.GET.get('local') == '1'
        
        def run_backup():
            try:
                perform_media_backup(local_only=is_local)
            except Exception as e:
                logger.error(f"Media backup failed: {e}")
                
        threading.Thread(target=run_backup, daemon=True).start()
        self.message_user(request, "Media backup started in background.", level=messages.INFO)
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '../'))

    def download_media(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj or obj.status != 'success':
            raise Http404("Backup not found.")
        
        try:
            if obj.storage_location.startswith('local:'):
                file_path = Path(obj.storage_location.split('local:')[1])
                return FileResponse(file_path.open('rb'), as_attachment=True, filename=file_path.name, content_type='application/zip')
            elif obj.storage_location.startswith('dropbox:'):
                remote_path = obj.storage_location.split('dropbox:')[1]
                storage = DropboxStorage()
                temp_file = Path(tempfile.gettempdir()) / Path(remote_path).name
                storage.download(remote_path, str(temp_file))
                return FileResponse(temp_file.open('rb'), as_attachment=True, filename=temp_file.name, content_type='application/zip')
        except Exception as e:
            self.message_user(request, f"Download failed: {str(e)}", level=messages.ERROR)
            return HttpResponseRedirect("../../")

    def restore_media(self, request, object_id):
        obj : MediaBackupRecord = self.get_object(request, object_id)
        record = MediaRestoreRecord.objects.create(source=f"Media Backup {obj.id}", status='pending')
        
        def run_restore():
            file_path_to_restore = None
            temp_file = None
            try:
                if obj.storage_location.startswith('local:'):
                    file_path_to_restore = obj.storage_location.split('local:')[1]
                elif obj.storage_location.startswith('dropbox:'):
                    remote_path = obj.storage_location.split('dropbox:')[1]
                    storage = DropboxStorage()
                    temp_file = Path(tempfile.gettempdir()) / Path(remote_path).name
                    storage.download(remote_path, str(temp_file))
                    file_path_to_restore = str(temp_file)
                
                if file_path_to_restore:
                    perform_media_restore(file_path_to_restore, record_id=record.id)
            except Exception as e:
                record.status = 'failed'
                record.error_message = str(e)
                record.save()
            finally:
                if temp_file: temp_file.unlink(missing_ok=True)

        threading.Thread(target=run_restore, daemon=True).start()
        self.message_user(request, "Media restore started. Viewing logs...", level=messages.INFO)
        return HttpResponseRedirect(reverse('admin:django_db_backups_mediarestorerecord_change', args=[record.id]))

    def upload_restore_media(self, request):
        if request.method == 'POST' and request.FILES.get('media_zip'):
            uploaded_file = request.FILES['media_zip']
            temp_file = Path(tempfile.gettempdir()) / uploaded_file.name
            
            try:
                with temp_file.open('wb+') as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)
                # Synchronous Validation
                validate_media_backup(temp_file)
            except Exception as e:
                temp_file.unlink(missing_ok=True)
                self.message_user(request, f"Error: {str(e)}", level=messages.ERROR)
                return HttpResponseRedirect(".")

            record = MediaRestoreRecord.objects.create(source=f"Uploaded: {uploaded_file.name}", status='pending')

            def run_uploaded_restore():
                try:
                    perform_media_restore(str(temp_file), record_id=record.id)
                except Exception:
                    pass
                finally:
                    temp_file.unlink(missing_ok=True)

            threading.Thread(target=run_uploaded_restore, daemon=True).start()
            self.message_user(request, "Media restore started. Viewing logs...", level=messages.INFO)
            return HttpResponseRedirect(reverse('admin:django_db_backups_mediarestorerecord_change', args=[record.id]))

        context = dict(self.admin_site.each_context(request))
        return render(request, 'admin/django_db_backups/mediabackuprecord/media_upload_restore.html', context)

@admin.register(MediaRestoreRecord)
class MediaRestoreRecordAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'source', 'status')
    readonly_fields = ('created_at', 'source', 'status', 'error_message', 'logs')
    def has_add_permission(self, request): return False
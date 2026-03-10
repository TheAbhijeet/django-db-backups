import uuid
from django.db import models
from django.forms import ValidationError

class BackupRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]

    db_type = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    size_bytes = models.BigIntegerField(default=0)
    storage_location = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Backup Log"
        verbose_name_plural = "Backup Logs"

    def __str__(self):
        return f"{self.db_type} backup at {self.created_at} ({self.status})"

class RestoreRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]

    source = models.CharField(max_length=255, help_text="e.g. Local file path, Uploaded file name, or Snapshot ID")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    logs = models.TextField(blank=True, help_text="Detailed logs of the restore process")
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Restore Log"
        verbose_name_plural = "Restore Logs"

    def __str__(self):
        return f"Restore from {self.source} at {self.created_at}"


class MediaBackupRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    size_bytes = models.BigIntegerField(default=0)
    storage_location = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=BackupRecord.STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Media Backup Log"
        verbose_name_plural = "Media Backup Logs"

    def __str__(self):
        return f"Media backup at {self.created_at} ({self.status})"

class MediaRestoreRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=RestoreRecord.STATUS_CHOICES, default='pending')
    logs = models.TextField(blank=True)
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Media Restore Log"
        verbose_name_plural = "Media Restore Logs"

    def __str__(self):
        return f"Media Restore from {self.source} at {self.created_at}"

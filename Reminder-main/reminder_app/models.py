import uuid
import os
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

def _default_time():
    """Return current time as a time object — safe default for TimeField."""
    return timezone.now().time()

def reminder_directory_path(instance, filename):
    """
    Production File Storage: 
    Organizes files into attachments/user_<id>/YYYY/MM/DD/<uuid>_filename
    Prevents file system bloat and naming collisions.
    """
    ext = filename.split('.')[-1]
    unique_filename = f"{uuid.uuid4().hex}.{ext}"
    user_id = instance.user.id if instance.user else 'anonymous'
    return f'attachments/user_{user_id}/{timezone.now().strftime("%Y/%m/%d")}/{unique_filename}'

class Category(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]
    name = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    color = models.CharField(max_length=7, default="#6366F1")

    def __str__(self):
        return self.name

class Reminder(models.Model):
    # --- Audit Trail ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Retry System for Scheduler ---
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)

    # --- Basic Info ---
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    subject = models.CharField(max_length=255) 
    purpose = models.TextField(blank=True, default="") 
    
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="reminders"
    )
    
    # --- File Attachment ---
    # FIXED: Replaced static string with dynamic directory path function
    attachment = models.FileField(upload_to=reminder_directory_path, blank=True, null=True)

    # --- Emails ---
    email_to = models.TextField() 
    email_cc = models.TextField(blank=True, default="")

    # --- Timing ---
    start_date = models.DateField(default=timezone.localdate)
    time = models.TimeField(default=_default_time)
    next_trigger = models.DateTimeField(null=True, blank=True, db_index=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    # --- Recurrence ---
    RECURRENCE_CHOICES = [
        ("once", "One Time"),
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
    ]
    recurrence_type = models.CharField(max_length=10, choices=RECURRENCE_CHOICES, default="once")
    interval = models.IntegerField(default=1)

    # Mode fields
    daily_mode = models.CharField(max_length=20, blank=True, default="")
    hour_interval = models.IntegerField(null=True, blank=True)
    by_weekday = models.CharField(max_length=50, blank=True, default="")
    monthly_mode = models.CharField(max_length=20, blank=True, default="")
    by_monthday = models.IntegerField(null=True, blank=True)
    by_setpos = models.IntegerField(null=True, blank=True)
    yearly_mode = models.CharField(max_length=20, blank=True, default="")
    by_month = models.IntegerField(null=True, blank=True)

    range_type = models.CharField(max_length=20, blank=True, default="")

    # --- Limits ---
    end_date = models.DateField(null=True, blank=True)
    occurrence_count = models.IntegerField(null=True, blank=True)
    sent_count = models.IntegerField(default=0)

    # --- Status ---
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('notified', 'Notified'),
        ('overdue', 'Overdue'),
        ('completed', 'Completed'),
        ('paused', 'Paused'),
        ('failed', 'Failed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'next_trigger']),
        ]

    def __str__(self):
        return f"{self.title} ({self.user.username})"
    
class ActivityLog(models.Model):
    LEVEL_CHOICES = [
        ('INFO', 'Information / Activity'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='INFO')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    path = models.CharField(max_length=255, default='/')
    method = models.CharField(max_length=10, default='GET')
    status_code = models.IntegerField(default=200)
    message = models.TextField(blank=True, default="")
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        user_display = self.user.username if self.user else "System"
        # Format: INFO | admin | /dashboard/ | 2026-04-14 04:52:35...
        return f"{self.level} | {user_display} | {self.path} | {self.timestamp}"

class FAQ(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]
    question = models.CharField(max_length=255)
    answer = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.question
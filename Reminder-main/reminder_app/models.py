from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import datetime, time as dt_time

from .recurrence import make_aware_safe


# ======================================
# CATEGORY MASTER MODEL
# ======================================
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


# ======================================
# REMINDER MODEL
# ======================================

def _default_time():
    """Return current time as a time object — safe default for TimeField."""
    return timezone.now().time()


class Reminder(models.Model):
    # --- Retry System for Scheduler ---
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)

    # --- Basic Info ---
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    subject = models.CharField(max_length=255, blank=True, null=True)
    purpose = models.TextField(blank=True, null=True)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="reminders"
    )
    
    # --- File Attachment ---
    # NEW: Added FileField to handle file uploads
    attachment = models.FileField(upload_to='attachments/', blank=True, null=True)

    # --- Emails ---
    email_to = models.TextField()
    email_cc = models.TextField(blank=True, null=True)

    # --- Timing ---
    start_date = models.DateField(default=timezone.localdate)
    time = models.TimeField(default=_default_time)
    next_trigger = models.DateTimeField(null=True, blank=True, db_index=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    # FIX: Added notified_at to track when a reminder was last set to 'notified'.
    # This enables a timeout/recovery path: if a reminder stays 'notified' for
    # too long (e.g. scheduler crashed after send but before advancing next_trigger),
    # a management command or periodic task can detect and requeue it.
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
    daily_mode = models.CharField(max_length=20, blank=True)
    hour_interval = models.IntegerField(null=True, blank=True)
    by_weekday = models.CharField(max_length=50, blank=True)
    monthly_mode = models.CharField(max_length=20, blank=True)
    by_monthday = models.IntegerField(null=True, blank=True)
    by_setpos = models.IntegerField(null=True, blank=True)
    yearly_mode = models.CharField(max_length=20, blank=True)
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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    # ======================================
    # LOGIC METHODS
    # ======================================

    def update_status(self):
        """
        Update status based on time and execution state.

        NOTE: This method only mutates self.status in memory.
        Callers must call save() separately to persist the change.

        FIX: Added 'notified' timeout recovery — if a reminder has been stuck
        in 'notified' for more than 10 minutes (scheduler likely crashed after
        sending but before advancing next_trigger), flip it back to 'active'
        so it can be requeued. This prevents permanent 'notified' limbo.
        """
        now_dt = timezone.now()
        today_date = timezone.localdate()

        # Never override paused or failed — these are manually set states
        if self.status in ("paused", "failed"):
            return

        # 1. Check if it should be completed by end date
        if self.end_date and today_date > self.end_date:
            self.status = "completed"
            return

        # 2. Use 'is not None' instead of truthiness check to handle occurrence_count=0 safely
        if self.occurrence_count is not None and self.sent_count >= self.occurrence_count:
            self.status = "completed"
            return

        # 3. Check if one-time reminder is already sent
        if self.recurrence_type == "once" and self.last_sent_at:
            self.status = "completed"
            return

        # 4. FIX: Recovery for stuck 'notified' reminders.
        #    If the scheduler set notified_at but never advanced next_trigger
        #    (e.g. crashed mid-transaction), reactivate after a 10-minute grace period.
        if self.status == "notified":
            if self.notified_at and (now_dt - self.notified_at).total_seconds() > 600:
                self.status = "active"
                self.notified_at = None
                # Fall through so remaining checks can set overdue if needed
            else:
                return

        # 5. Explicitly set overdue when next_trigger is in the past and reminder is active
        if self.next_trigger and self.next_trigger < now_dt:
            self.status = "overdue"
            return

        # 6. Trigger is in the future — reminder is active
        if self.next_trigger and self.next_trigger > now_dt:
            self.status = "active"

    def save(self, *args, **kwargs):
        # Auto-calculate next_trigger on the very first save if not set
        if not self.next_trigger:
            dt_combined = datetime.combine(self.start_date, self.time)
            self.next_trigger = make_aware_safe(dt_combined)

        # Always update status before saving
        self.update_status()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ["next_trigger"]


# ======================================
# ACTIVITY LOG MODEL
# ======================================
class ActivityLog(models.Model):
    STATUS_CHOICES = [
        ("success", "Success"),
        ("error", "Error"),
    ]
    ACTION_CHOICES = [
        ("login", "Login"),
        ("logout", "Logout"),
        ("create", "Created Reminder"),
        ("edit", "Edited Reminder"),
        ("delete", "Deleted Reminder"),
        ("pause", "Paused Reminder"),
        ("resume", "Resumed Reminder"),
        ("email_sent", "Email Sent"),
        ("create_user", "Created User"),
        ("edit_user", "Edited User"),
        ("delete_user", "Deleted User"),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="success")
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.action} - {self.status}"
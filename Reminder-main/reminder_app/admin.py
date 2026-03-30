from django.contrib import admin
from .models import Reminder, ActivityLog


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "status", "next_trigger", "last_sent_at")
    list_filter = ("status", "recurrence_type")
    search_fields = ("title", "subject")


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "description", "timestamp")
    list_filter = ("action", "timestamp")
    search_fields = ("user__username", "description")
    ordering = ("-timestamp",)
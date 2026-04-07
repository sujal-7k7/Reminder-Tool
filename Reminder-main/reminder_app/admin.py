from django.contrib import admin
from .models import Reminder, ActivityLog, FAQ, Category

# ======================================
# CATEGORY ADMIN
# ======================================
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'color', 'created_at')
    list_editable = ('status',)
    search_fields = ('name',)
    list_filter = ('status',)
    list_per_page = 50 # Prevents loading too many rows at once

# ======================================
# REMINDER ADMIN
# ======================================
@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "category", "status", "next_trigger", "last_sent_at")
    list_filter = ("status", "recurrence_type", "category")
    search_fields = ("title", "subject", "user__username") # Added user search
    list_select_related = ("user", "category") # CRITICAL: Prevents N+1 database queries
    list_per_page = 50
    date_hierarchy = "next_trigger" # Adds a date drill-down navigation

# ======================================
# ACTIVITY LOG ADMIN
# ======================================
@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "ip_address", "timestamp")
    list_filter = ("action", "timestamp")
    search_fields = ("user__username", "action") 
    ordering = ("-timestamp",)
    list_select_related = ("user",) # CRITICAL: Prevents N+1 database queries
    list_per_page = 100
    date_hierarchy = "timestamp"
    
    # CRITICAL: Make logs read-only in production
    def get_readonly_fields(self, request, obj=None):
        if obj: # If the object already exists, lock it down
            return ("user", "action", "ip_address", "timestamp")
        return self.readonly_fields

# ======================================
# FAQ ADMIN
# ======================================
@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ('question', 'status', 'created_at')
    list_editable = ('status',)
    search_fields = ('question', 'answer')
    list_filter = ('status',)
    list_per_page = 50
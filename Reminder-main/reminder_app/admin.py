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

# ======================================
# REMINDER ADMIN
# ======================================
@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    # Added "category" to list_display and list_filter
    list_display = ("title", "user", "category", "status", "next_trigger", "last_sent_at")
    list_filter = ("status", "recurrence_type", "category")
    search_fields = ("title", "subject")

# ======================================
# ACTIVITY LOG ADMIN
# ======================================
@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "description", "timestamp")
    list_filter = ("action", "timestamp")
    search_fields = ("user__username", "description")
    ordering = ("-timestamp",)

# ======================================
# FAQ ADMIN
# ======================================
@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    # This shows these columns in the admin list view
    list_display = ('question', 'is_active', 'sort_order', 'created_at')
    
    # This lets you quickly check/uncheck active status or change order without opening the item
    list_editable = ('is_active', 'sort_order')
    
    # Adds a search bar
    search_fields = ('question', 'answer')
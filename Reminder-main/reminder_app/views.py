from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.utils import timezone
from django.utils.timezone import now
from datetime import datetime
from django.db.models import Count
from django.core.mail import EmailMessage
from django.conf import settings
from django.contrib.auth.models import User
from .models import Reminder, Category, ActivityLog
from .forms import ReminderForm
from .recurrence import build_rrule
# FIX: Import send_reminder_email from utils (single source of truth).
# The duplicate definition that was in views.py has been removed.
from .utils import send_reminder_email
import logging


# =========================================================
# ACTIVITY LOGGER
# =========================================================

activity_logger = logging.getLogger("activity_logger")

def log_activity(user, action, description=""):
    username = "Anonymous"
    if user and hasattr(user, "username"):
        username = user.username
    try:
        ActivityLog.objects.create(
            user=user if user and user.is_authenticated else None,
            action=action,
            description=description
        )
    except Exception as e:
        logging.getLogger("error_logger").error(
            f"DB ActivityLog failed | User={username} | Action={action} | Error={str(e)}"
        )
    try:
        activity_logger.info(
            f"User={username} | Action={action} | Description={description}"
        )
    except Exception as e:
        logging.getLogger("error_logger").error(
            f"Activity file logging failed | Error={str(e)}"
        )


# =========================================================
# RECURRENCE PARTIAL VIEWS
# =========================================================

def recurrence_daily(request):
    return render(request, "reminders/recurrence/daily.html")

def recurrence_weekly(request):
    return render(request, "reminders/recurrence/weekly.html")

def recurrence_monthly(request):
    return render(request, "reminders/recurrence/monthly.html")

def recurrence_yearly(request):
    return render(request, "reminders/recurrence/yearly.html")


# ==========================================================
# CATEGORY
# ==========================================================

@login_required
@staff_member_required
def category_master(request):
    if request.method == "POST" and "add_category" in request.POST:
        name = request.POST.get("name")
        if name:
            Category.objects.get_or_create(name=name.strip())
        return redirect("category_master")

    if request.method == "POST" and "toggle_status" in request.POST:
        cat_id = request.POST.get("cat_id")
        category = get_object_or_404(Category, id=cat_id)
        category.status = "inactive" if category.status == "active" else "active"
        category.save()
        return redirect("category_master")

    if request.method == "POST" and "delete_category" in request.POST:
        cat_id = request.POST.get("cat_id")
        category = get_object_or_404(Category, id=cat_id)
        category.delete()
        return redirect("category_master")

    categories = Category.objects.all().order_by("-created_at")
    return render(request, "category_master.html", {"categories": categories})


# =========================================================
# AUTH
# =========================================================

def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            log_activity(user, "login", "User logged in")
            return redirect("dashboard")
        else:
            return render(request, "login.html", {"error": "Invalid username or password"})
    return render(request, "login.html")


def logout_view(request):
    if request.user.is_authenticated:
        log_activity(request.user, "logout", "User logged out")
    logout(request)
    return redirect("login")


# =========================================================
# DASHBOARD
# =========================================================

@login_required
def dashboard(request):
    reminders = Reminder.objects.filter(user=request.user).order_by('next_trigger', 'id')

    now_dt = timezone.now()
    today_date = timezone.localdate()
    reminders_to_update = []

    for reminder in reminders:
        original_status = reminder.status

        if reminder.end_date and today_date > reminder.end_date:
            reminder.status = "completed"
        elif reminder.recurrence_type == "once" and reminder.last_sent_at:
            reminder.status = "completed"
        elif reminder.next_trigger and reminder.next_trigger < now_dt and reminder.status == "active":
            reminder.status = "overdue"

        if reminder.status != original_status:
            reminders_to_update.append(reminder)

    if reminders_to_update:
        Reminder.objects.bulk_update(reminders_to_update, ['status'])

    total = reminders.count()
    today = reminders.filter(next_trigger__date=today_date).count()
    overdue = reminders.filter(status="overdue").count()

    interval_data = reminders.values("recurrence_type").annotate(count=Count("id")).order_by()
    status_data   = reminders.values("status").annotate(count=Count("id")).order_by()

    return render(request, "dashboard.html", {
        "reminders": reminders,
        "total": total,
        "today": today,
        "overdue": overdue,
        "interval_data": list(interval_data),
        "status_data": list(status_data),
    })


# =========================================================
# CONTACT
# =========================================================

def contact(request):
    if request.method == "POST":
        messages.success(request, "Your message has been sent successfully!")
        return redirect("contact")
    return render(request, "contact.html")


# =========================================================
# DELETE REMINDER
# =========================================================

@login_required
def delete_reminder(request, reminder_id):
    if request.method == "POST":
        reminder = get_object_or_404(Reminder, id=reminder_id, user=request.user)
        log_activity(request.user, "delete", f"Deleted reminder: {reminder.title}")
        reminder.delete()
        messages.success(request, "Reminder deleted successfully.")
    return redirect("dashboard")


# =========================================================
# SHARED: RECURRENCE next_trigger HELPER
# =========================================================

def _set_next_trigger(reminder, start_dt):
    """
    Calculate and assign next_trigger after saving recurrence fields.
    """
    if reminder.recurrence_type != "once":
        rule = build_rrule(reminder)
        if rule:
            reminder.next_trigger = rule.after(timezone.now(), inc=True)
    else:
        reminder.next_trigger = start_dt


# =========================================================
# CREATE REMINDER
# =========================================================

@login_required
def create_reminder(request):
    categories = Category.objects.filter(status="active")

    if request.method == "POST":
        form = ReminderForm(request.POST)

        if form.is_valid():
            reminder = form.save(commit=False)
            reminder.user = request.user

            start_dt = timezone.make_aware(
                datetime.combine(reminder.start_date, reminder.time)
            )

            # FIX: Set next_trigger BEFORE the first (and only) save so that
            # update_status() inside save() sees the correct next_trigger and
            # never briefly writes an incorrect status to the DB.
            # Previously: save() → (stale status written) → _set_next_trigger → save()
            # Now:        _set_next_trigger → save() once with correct next_trigger
            _set_next_trigger(reminder, start_dt)
            reminder.save()

            log_activity(request.user, "create", f"Created reminder: {reminder.title}")
            messages.success(request, f"Reminder '{reminder.title}' created successfully!")
            return redirect("dashboard")

        return render(request, "reminder_form.html", {
            "form": form,
            "categories": categories,
        })

    form = ReminderForm()
    return render(request, "reminder_form.html", {
        "form": form,
        "categories": categories,
    })


# =========================================================
# EDIT REMINDER
# =========================================================

@login_required
def edit_reminder(request, reminder_id):
    reminder   = get_object_or_404(Reminder, id=reminder_id, user=request.user)
    categories = Category.objects.filter(status="active")

    if request.method == "POST":
        form = ReminderForm(request.POST, instance=reminder)

        if form.is_valid():
            # Fetch original values directly from DB
            original_db = Reminder.objects.get(pk=reminder_id)
            original_start_dt = timezone.make_aware(
                datetime.combine(original_db.start_date, original_db.time)
            )

            updated = form.save(commit=False)
            new_start_dt = timezone.make_aware(
                datetime.combine(updated.start_date, updated.time)
            )

            if new_start_dt != original_start_dt and new_start_dt <= timezone.now():
                form.add_error(None, "New start time cannot be in the past.")
                return render(request, "reminder_form.html", {
                    "form": form,
                    "reminder": reminder,
                    "categories": categories,
                })

            # FIX: Set next_trigger BEFORE the first (and only) save so that
            # update_status() inside save() sees the correct next_trigger.
            # Also: log_activity is now called AFTER save() so the activity log
            # is only written once the DB write has actually succeeded.
            _set_next_trigger(updated, new_start_dt)
            updated.save()

            log_activity(request.user, "edit", f"Edited reminder: {updated.title}")
            messages.success(request, f"Reminder '{updated.title}' updated successfully!")
            return redirect("dashboard")

        return render(request, "reminder_form.html", {
            "form": form,
            "reminder": reminder,
            "categories": categories,
        })

    form = ReminderForm(instance=reminder)
    return render(request, "reminder_form.html", {
        "form": form,
        "reminder": reminder,
        "categories": categories,
    })


# =========================================================
# TOGGLE PAUSE
# =========================================================

@login_required
def toggle_pause(request, reminder_id):
    if request.method == "POST":
        reminder = get_object_or_404(Reminder, id=reminder_id, user=request.user)
        if reminder.status == "paused":
            reminder.status = "active"
            log_activity(request.user, "resume", f"Resumed reminder: {reminder.title}")
            if reminder.next_trigger and reminder.next_trigger < timezone.now():
                reminder.next_trigger = timezone.now()
        else:
            reminder.status = "paused"
            log_activity(request.user, "pause", f"Paused reminder: {reminder.title}")
        reminder.save()
    return redirect("dashboard")


# =========================================================
# USERS
# =========================================================

@login_required
@staff_member_required
def users_list(request):
    users = User.objects.all().order_by("-date_joined")
    return render(request, "users_list.html", {"users": users})


@login_required
def profile(request):
    return render(request, "profile.html", {"user_obj": request.user})


@login_required
@staff_member_required
def create_user(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()
        role     = request.POST.get("role", "user")

        if not username or not password:
            messages.error(request, "Username and password are required.")
            return redirect("create_user")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect("create_user")

        user = User.objects.create_user(username=username, password=password)
        user.is_staff = (role == "admin")
        user.save()

        log_activity(request.user, "create_user", f"Created user {username}")
        messages.success(request, f"User '{username}' created successfully!")
        return redirect("users_list")

    return render(request, "create_user.html")


@login_required
@staff_member_required
def edit_user(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        role     = request.POST.get("role", "user")
        password = request.POST.get("password", "").strip()

        if user.is_superuser and role != "admin":
            messages.error(request, "Superuser role cannot be changed.")
            return redirect("users_list")

        if User.objects.exclude(id=user_id).filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect("users_list")

        user.username = username
        user.is_staff = (role == "admin")

        if password:
            user.set_password(password)

        user.save()
        log_activity(request.user, "edit_user", f"Updated user {user.username}")
        messages.success(request, f"User '{username}' updated successfully!")
        return redirect("users_list")

    return render(request, "create_user.html", {
        "edit_mode": True,
        "edit_user": user
    })


@login_required
@staff_member_required
def delete_user(request, user_id):
    if request.method == "POST":
        user = get_object_or_404(User, id=user_id)

        if user.is_superuser:
            messages.error(request, "Superuser cannot be deleted.")
            return redirect("users_list")

        if request.user.id == user_id:
            messages.error(request, "You cannot delete your own account.")
            return redirect("users_list")

        username = user.username
        log_activity(request.user, "delete_user", f"Deleted user {username}")
        user.delete()
        messages.success(request, f"User '{username}' deleted successfully!")

    return redirect("users_list")


@login_required
def calendar_view(request):
    reminders = Reminder.objects.filter(
        user=request.user, next_trigger__isnull=False
    ).exclude(status="failed")
    categories = Category.objects.filter(status="active")

    events = []
    for r in reminders:
        color = '#6366f1'
        if r.status == 'completed':   color = '#9ca3af'
        elif r.status == 'overdue':   color = '#ef4444'
        elif r.status == 'paused':    color = '#f59e0b'

        events.append({
            'title': r.title,
            'start': r.next_trigger.isoformat(),
            'color': color,
            'extendedProps': {
                'subject':   r.subject or 'No Subject',
                'purpose':   r.purpose or 'No Purpose provided',
                'category':  r.category.name if r.category else 'General',
                'email_to':  r.email_to,
                'email_cc':  r.email_cc or 'None',
                'status':    r.status,
                'time':      r.time.strftime("%I:%M %p"),
            }
        })
    return render(request, "calendar_view.html", {"events": events, "categories": categories})
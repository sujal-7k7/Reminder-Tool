from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta
from django.db.models import Count
from django.contrib.auth.models import User
from collections import Counter  # FIXED: Moved to top of file
from .models import Reminder, Category, ActivityLog, FAQ
from .forms import ReminderForm
from .recurrence import build_rrule
from .utils import send_reminder_email
import logging

activity_logger = logging.getLogger("activity_logger")
error_logger    = logging.getLogger("error_logger")


def log_activity(user, action, description="", status="success"):
    username = "Anonymous"
    if user and hasattr(user, "username"):
        username = user.username
    try:
        ActivityLog.objects.create(
            user=user if user and user.is_authenticated else None,
            action=action,
            # Removed description and status to match our earlier model fixes
            # We combine them into the action field like we did in the scheduler
        )
    except Exception as e:
        error_logger.error(
            f"DB ActivityLog failed | User={username} | Action={action} | Error={str(e)}"
        )
    try:
        activity_logger.info(
            f"User={username} | Action={action} | Status={status} | Description={description}"
        )
    except Exception as e:
        error_logger.error(f"Activity file logging failed | Error={str(e)}")


@login_required
@staff_member_required
def category_master(request):
    if request.method == "POST" and "add_category" in request.POST:
        name = request.POST.get("name", "").strip()
        color = request.POST.get("color", "#6366F1") 
        if name:
            Category.objects.get_or_create(name=name, defaults={'color': color})
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

    categories = Category.objects.annotate(
    reminder_count=Count('reminders')
    ).order_by("-created_at")
    return render(request, "category_master.html", {"categories": categories})


def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            log_activity(user, "login", "User logged in")
            return redirect("dashboard")
        return render(request, "login.html", {"error": "Invalid username or password"})
    return render(request, "login.html")


def logout_view(request):
    if request.user.is_authenticated:
        log_activity(request.user, "logout", "User logged out")
    logout(request)
    return redirect("login")


@login_required
def dashboard(request):
    # FIXED: Added select_related to prevent N+1 queries in the dashboard template
    reminders = list(
        Reminder.objects.select_related('category')
        .filter(user=request.user)
        .order_by('next_trigger', 'id')
    )

    now_dt     = timezone.now()
    today_date = timezone.localdate()
    reminders_to_update = []

    for reminder in reminders:
        original_status = reminder.status
        new_status      = original_status

        if reminder.end_date and today_date > reminder.end_date:
            new_status = "completed"
        elif reminder.recurrence_type == "once" and reminder.last_sent_at:
            new_status = "completed"
        elif (
            reminder.next_trigger
            and reminder.next_trigger < now_dt
            and reminder.status == "active"
        ):
            new_status = "overdue"

        if new_status != original_status:
            reminder.status = new_status
            reminders_to_update.append(reminder)

    if reminders_to_update:
        Reminder.objects.bulk_update(reminders_to_update, ['status'])

    total   = len(reminders)
    today   = sum(
        1 for r in reminders
        if r.next_trigger and r.next_trigger.date() == today_date
    )
    overdue = sum(1 for r in reminders if r.status == "overdue")

    interval_counter = Counter(r.recurrence_type for r in reminders)
    status_counter   = Counter(r.status for r in reminders)
    interval_data = [{"recurrence_type": k, "count": v} for k, v in interval_counter.items()]
    status_data   = [{"status": k, "count": v} for k, v in status_counter.items()]

    return render(request, "dashboard.html", {
        "reminders":     reminders,
        "total":         total,
        "today":         today,
        "overdue":       overdue,
        "interval_data": interval_data,
        "status_data":   status_data,
    })


@login_required
def delete_reminder(request, reminder_id):
    if request.method == "POST":
        reminder = get_object_or_404(Reminder, id=reminder_id, user=request.user)
        title = reminder.title
        reminder.delete()
        log_activity(request.user, "delete", f"Deleted reminder: {title}")
        messages.success(request, "Reminder deleted successfully.")
    return redirect("dashboard")


def _set_next_trigger(reminder, start_dt):
    if reminder.recurrence_type != "once":
        rule = build_rrule(reminder)
        if rule:
            reminder.next_trigger = rule.after(start_dt - timedelta(seconds=1), inc=True)
        else:
            reminder.next_trigger = None
    else:
        reminder.next_trigger = start_dt


@login_required
def create_reminder(request):
    categories = Category.objects.filter(status="active")

    if request.method == "POST":
        form = ReminderForm(request.POST, request.FILES)
        if form.is_valid():
            reminder = form.save(commit=False)
            reminder.user = request.user
            start_dt = timezone.make_aware(
                datetime.combine(reminder.start_date, reminder.time)
            )
            _set_next_trigger(reminder, start_dt)
            reminder.save()
            log_activity(request.user, "create", f"Created reminder: {reminder.title}")
            messages.success(request, f"Reminder '{reminder.title}' created successfully!")
            return redirect("dashboard")

        return render(request, "reminder_form.html", {
            "form": form, "reminder": None, "categories": categories,
        })

    form = ReminderForm()
    return render(request, "reminder_form.html", {
        "form": form, "reminder": None, "categories": categories,
    })


@login_required
def edit_reminder(request, reminder_id):
    reminder   = get_object_or_404(Reminder, id=reminder_id, user=request.user)
    categories = Category.objects.filter(status="active")

    if request.method == "POST":
        form = ReminderForm(request.POST, request.FILES, instance=reminder)
        if form.is_valid():
            original_start_dt = timezone.make_aware(
                datetime.combine(reminder.start_date, reminder.time)
            )
            updated      = form.save(commit=False)
            new_start_dt = timezone.make_aware(
                datetime.combine(updated.start_date, updated.time)
            )

            cutoff = timezone.now() - timedelta(minutes=2)
            if new_start_dt != original_start_dt and new_start_dt < cutoff:
                form.add_error(None, "New start time cannot be in the past.")
                return render(request, "reminder_form.html", {
                    "form": form, "reminder": reminder, "categories": categories,
                })

            _set_next_trigger(updated, new_start_dt)
            updated.save()
            log_activity(request.user, "edit", f"Edited reminder: {updated.title}")
            messages.success(request, f"Reminder '{updated.title}' updated successfully!")
            return redirect("dashboard")

        return render(request, "reminder_form.html", {
            "form": form, "reminder": reminder, "categories": categories,
        })

    form = ReminderForm(instance=reminder)
    return render(request, "reminder_form.html", {
        "form": form, "reminder": reminder, "categories": categories,
    })


@login_required
def toggle_pause(request, reminder_id):
    if request.method == "POST":
        reminder = get_object_or_404(Reminder, id=reminder_id, user=request.user)

        if reminder.status in ("completed", "failed"):
            messages.error(request, "Cannot pause or resume a completed or failed reminder.")
            return redirect("dashboard")

        if reminder.status == "paused":
            reminder.status = "active"
            if reminder.next_trigger and reminder.next_trigger < timezone.now():
                reminder.next_trigger = timezone.now()
            reminder.save()
            log_activity(request.user, "resume", f"Resumed reminder: {reminder.title}")
        else:
            reminder.status = "paused"
            reminder.save()
            log_activity(request.user, "pause", f"Paused reminder: {reminder.title}")

    return redirect("dashboard")


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
        email    = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        role = request.POST.get("role", "user")

        if not username or not password:
            messages.error(request, "Username and password are required.")
            return redirect("create_user")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect("create_user")

        user = User.objects.create_user(username=username, email=email, password=password)
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
        email    = request.POST.get("email", "").strip()
        role     = request.POST.get("role", "user")
        password = request.POST.get("password", "")

        if not username:
            messages.error(request, "Username cannot be empty.")
            return redirect("users_list")

        # FIXED: CRITICAL SECURITY PATCH (Privilege Escalation)
        # Prevents staff from editing superuser accounts, preventing an account takeover.
        if user.is_superuser and not request.user.is_superuser:
            messages.error(request, "You do not have permission to edit a superuser account.")
            return redirect("users_list")

        if User.objects.exclude(id=user_id).filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect("users_list")

        user.username = username
        user.email    = email
        user.is_staff = (role == "admin")

        if password:
            user.set_password(password)

        user.save()
        log_activity(request.user, "edit_user", f"Updated user {username}")
        messages.success(request, f"User '{username}' updated successfully!")
        return redirect("users_list")

    return render(request, "create_user.html", {"edit_mode": True, "edit_user": user})


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
        user.delete()
        log_activity(request.user, "delete_user", f"Deleted user {username}")
        messages.success(request, f"User '{username}' deleted successfully!")

    return redirect("users_list")


@login_required
def calendar_view(request):
    # Fetch user-specific reminders that have a scheduled trigger
    reminders = Reminder.objects.select_related('category').filter(
        user=request.user, 
        next_trigger__isnull=False
    ).exclude(status="failed")
    
    categories = Category.objects.filter(status="active")

    STATUS_COLORS = {
        'completed': '#22c55e',  # Vibrant Green
        'overdue':   '#ef4444',  # Alert Red
        'notified':  '#3b82f6',  # Action Blue
        'active':    '#6366f1',  # Standard Indigo
        'paused':    '#f59e0b',  # Warning Amber
    }

    events = []
    for r in reminders:
        status_color = STATUS_COLORS.get(r.status, '#6366f1')

        events.append({
            'title':           r.title,
            'start':           r.next_trigger.isoformat(),
            'backgroundColor': status_color,
            'borderColor':     status_color,
            'textColor':       '#ffffff', 
            'extendedProps': {
                'subject':  r.subject or 'No Subject',
                'category': r.category.name if r.category else 'General',
                'status':   r.status.upper(), 
                'time':     r.time.strftime("%I:%M %p"),
                
                # ==========================================
                # FIXED: Added the missing fields for the JS Modal
                # ==========================================
                'purpose':  r.purpose,
                'email_to': r.email_to,
                'email_cc': r.email_cc,
            },
        })

    return render(request, "calendar_view.html", {
        "events": events, 
        "categories": categories,
    })


@login_required
@staff_member_required
def faq_master(request):
    if request.method == "POST" and "add_faq" in request.POST:
        question = request.POST.get("question", "").strip()
        answer = request.POST.get("answer", "").strip()
        if question and answer:
            FAQ.objects.create(question=question, answer=answer)
            messages.success(request, "FAQ added successfully.")
        return redirect("faq_master")

    if request.method == "POST" and "toggle_status" in request.POST:
        faq_id = request.POST.get("faq_id")
        faq = get_object_or_404(FAQ, id=faq_id)
        faq.status = "inactive" if faq.status == "active" else "active"
        faq.save()
        messages.success(request, f"FAQ '{faq.question[:15]}...' status updated.")
        return redirect("faq_master")

    if request.method == "POST" and "delete_faq" in request.POST:
        faq_id = request.POST.get("faq_id")
        faq = get_object_or_404(FAQ, id=faq_id)
        faq.delete()
        messages.success(request, "FAQ deleted successfully.")
        return redirect("faq_master")

    faqs = FAQ.objects.all().order_by("-created_at")
    return render(request, "faq_master.html", {"faqs": faqs})


def faq_view(request):
    faqs = FAQ.objects.filter(status='active').order_by('-created_at')
    return render(request, 'faq.html', {'faqs': faqs})
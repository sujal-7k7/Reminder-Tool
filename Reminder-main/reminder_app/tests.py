from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta, date, time
from django.core.files.uploadedfile import SimpleUploadedFile

from reminder_app.models import Category, Reminder, ActivityLog, FAQ
from reminder_app.forms import ReminderForm
from reminder_app.recurrence import build_rrule


class ModelIntegrityTests(TestCase):
    """Tests to ensure our database schema handles edge cases gracefully."""
    
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.category = Category.objects.create(name="Work", color="#ff0000")

    def test_activity_log_survives_user_deletion(self):
        """CRITICAL FIX: Audit logs must survive when a user is deleted (SET_NULL)."""
        log = ActivityLog.objects.create(user=self.user, action="Test Action")
        self.user.delete()
        log.refresh_from_db()
        
        self.assertIsNone(log.user)
        self.assertEqual(log.action, "Test Action")
        # Ensure the string representation doesn't crash on a null user
        self.assertTrue("System Log" in str(log))

    def test_reminder_default_values(self):
        """Ensure the reminder defaults allow for safe background scheduling."""
        reminder = Reminder.objects.create(
            user=self.user,
            title="Test Task",
            email_to="test@test.com"
        )
        self.assertEqual(reminder.retry_count, 0)
        self.assertEqual(reminder.status, "active")
        self.assertEqual(reminder.interval, 1)


class ReminderFormTests(TestCase):
    """Tests to ensure malicious or glitchy payloads don't crash the worker."""

    def test_email_sanitization_comma_and_semicolon(self):
        """CRITICAL FIX: Form must accept both commas and semicolons without crashing."""
        data = {
            'title': 'Test', 'subject': 'Test', 
            'start_date': date.today(), 'time': time(12, 0),
            'email_to': 'user1@test.com, user2@test.com; user3@test.com',
            'recurrence_type': 'once'
        }
        form = ReminderForm(data=data)
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data['email_to'], 
            'user1@test.com; user2@test.com; user3@test.com'
        )

    def test_safe_type_casting_for_intervals(self):
        """CRITICAL FIX: Form must not throw ValueError 500 crashes on bad ints."""
        data = {
            'title': 'Test', 'subject': 'Test', 
            'start_date': date.today(), 'time': time(12, 0),
            'email_to': 'test@test.com',
            'recurrence_type': 'daily',
            'daily_mode': 'interval',
            'interval': 'invalid_string', # Malicious/Glitchy frontend payload
            'range_type': 'end_by',
            'end_date': date.today() + timedelta(days=5)
        }
        form = ReminderForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('interval', form.errors)

    def test_file_extension_spoofing_defense(self):
        """CRITICAL FIX: Check MIME type, not just extension."""
        # Create a fake executable disguised as a PDF
        fake_pdf = SimpleUploadedFile("virus.pdf", b"MZ\x90\x00\x03\x00\x00\x00", content_type="application/x-msdownload")
        
        data = {
            'title': 'Test', 'subject': 'Test', 'email_to': 'test@test.com',
            'start_date': date.today(), 'time': time(12, 0), 'recurrence_type': 'once'
        }
        form = ReminderForm(data=data, files={'attachment': fake_pdf})
        self.assertFalse(form.is_valid())
        self.assertIn('attachment', form.errors)


class ViewSecurityTests(TestCase):
    """Tests to ensure access control and N+1 query fixes are active."""

    def setUp(self):
        self.client = Client()
        self.normal_user = User.objects.create_user(username="normal", password="password")
        self.staff_user = User.objects.create_user(username="staff", password="password", is_staff=True)
        self.super_user = User.objects.create_superuser(username="admin", password="password")

    def test_dashboard_login_required(self):
        """Anonymous users must be redirected."""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('login')))

    def test_category_master_staff_protection(self):
        """Normal users cannot access master settings."""
        self.client.login(username="normal", password="password")
        response = self.client.get(reverse('category_master'))
        # Should redirect to login or show 403 Forbidden based on your staff_member_required setup
        self.assertEqual(response.status_code, 302) 

    def test_prevent_superuser_privilege_escalation(self):
        """CRITICAL FIX: Staff cannot edit a superuser to steal their account."""
        self.client.login(username="staff", password="password")
        # Try to POST a new password to the superuser's edit page
        response = self.client.post(reverse('edit_user', args=[self.super_user.id]), {
            'username': 'admin', 'email': 'admin@test.com', 
            'role': 'admin', 'password': 'hacked'
        })
        
        self.super_user.refresh_from_db()
        self.assertTrue(self.super_user.check_password("password")) # Password should NOT have changed
        self.assertFalse(self.super_user.check_password("hacked"))


class RecurrenceEngineTests(TestCase):
    """Tests to guarantee the mathematical background worker never crashes."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        
    def test_zero_interval_crash_prevention(self):
        """CRITICAL FIX: dateutil crashes if interval is < 1. We must force max(1)."""
        reminder = Reminder(
            user=self.user, title="Test", start_date=date.today(), time=time(12, 0),
            recurrence_type="daily", daily_mode="interval", interval=0, # Database anomaly
            range_type="end_after", occurrence_count=5
        )
        rule = build_rrule(reminder)
        self.assertIsNotNone(rule) # Must not crash
        self.assertEqual(rule._interval, 1) # Must safely default to 1

    def test_bysetpos_zero_crash_prevention(self):
        """CRITICAL FIX: dateutil crashes if bysetpos is 0."""
        reminder = Reminder(
            user=self.user, title="Test", start_date=date.today(), time=time(12, 0),
            recurrence_type="monthly", monthly_mode="nth_weekday", by_setpos=0, by_weekday="0",
            range_type="end_after", occurrence_count=5
        )
        rule = build_rrule(reminder)
        self.assertIsNotNone(rule) # Must not crash
        
def test_email_sanitization_semicolons_only(self):
        """CRITICAL FIX: Form must accept semicolons and reject invalid structures."""
        data = {
            'title': 'Test', 'subject': 'Test', 
            # FIXED: Passing dates as strings to mimic a real HTML form submission
            'start_date': '2026-04-06', 
            'time': '12:00',
            'email_to': 'user1@test.com; user2@test.com; user3@test.com',
            'recurrence_type': 'once'
        }
        form = ReminderForm(data=data)
        
        # Added form.errors to the assert so if it fails, it prints EXACTLY why
        self.assertTrue(form.is_valid(), f"Form failed with errors: {form.errors}") 
        self.assertEqual(
            form.cleaned_data['email_to'], 
            'user1@test.com; user2@test.com; user3@test.com'
        )

def test_file_extension_spoofing_defense(self):
        """CRITICAL FIX: Check strict MIME type, not just extension."""
        fake_pdf = SimpleUploadedFile("virus.pdf", b"MZ\x90\x00\x03\x00\x00\x00", content_type="application/x-msdownload")
        
        data = {
            'title': 'Test', 'subject': 'Test', 'email_to': 'test@test.com',
            # FIXED: Passing dates as strings
            'start_date': '2026-04-06', 'time': '12:00', 'recurrence_type': 'once'
        }
        form = ReminderForm(data=data, files={'attachment': fake_pdf})
        self.assertFalse(form.is_valid())
        self.assertIn('attachment', form.errors)
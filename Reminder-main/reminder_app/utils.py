import re
import html
import logging
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.utils.timezone import localtime
from reminder_app.models import ActivityLog

error_logger = logging.getLogger("error_logger")
logger = logging.getLogger("scheduler_logger")


def parse_emails(email_string):
    """
    Parse a semicolon-or-comma-separated email string into a deduplicated list
    of validated, lowercased addresses.

    BUG FIX: The original used a set() for deduplication, which destroys
    insertion order and makes recipient ordering non-deterministic across
    runs.  dict.fromkeys() deduplicates while preserving order.
    """
    if not email_string:
        return []

    seen = {}
    for raw in re.split(r"[;,]+", email_string):
        email = raw.strip().lower()
        if not email:
            continue
        try:
            validate_email(email)
            seen[email] = None          # dict.fromkeys-style dedup, order preserved
        except ValidationError:
            error_logger.warning(f"Invalid email skipped: {email}")

    return list(seen.keys())


def _log_activity(reminder, status, description):
    """
    Write an ActivityLog row, swallowing any DB errors so a logging failure
    never masks the real exception.

    BUG FIX: The original called ActivityLog.objects.create() directly inside
    the except block of send_reminder_email().  If the DB was down (which is
    often why email sending also fails), that second DB call raised a new
    exception that replaced the original one in the traceback, making the real
    failure invisible.
    """
    try:
        ActivityLog.objects.create(
            user=reminder.user,
            action="email_sent",
            description=description,
            status=status,
        )
    except Exception:
        # Log to file so the failure isn't completely silent, but don't re-raise
        error_logger.exception(
            f"ActivityLog write failed for Reminder ID {reminder.id} "
            f"(status={status}) — original email outcome is unaffected"
        )


def send_reminder_email(reminder):
    to_emails = parse_emails(reminder.email_to)
    cc_emails = parse_emails(reminder.email_cc)

    if not to_emails:
        error_logger.error(f"No valid recipients for Reminder ID {reminder.id}")
        raise ValueError("No valid recipient emails")

    subject = reminder.subject or f"Reminder: {reminder.title}"
    title         = html.escape(reminder.title   or "Reminder")
    purpose       = html.escape(reminder.purpose or "N/A")
    category_name = html.escape(reminder.category.name) if reminder.category else "N/A"

    # BUG FIX: escape formatted_time too.  The strftime path is safe, but the
    # fallback str(reminder.next_trigger) can contain timezone strings with
    # characters like '<' or '&' that would break the HTML body.
    formatted_time = "N/A"
    if reminder.next_trigger:
        try:
            local_time = localtime(reminder.next_trigger)
            formatted_time = local_time.strftime("%d %b %Y, %I:%M %p")
        except Exception:
            formatted_time = str(reminder.next_trigger)
    formatted_time = html.escape(formatted_time)

    text_content = (
        f"Reminder: {title}\n"
        f"Purpose: {purpose}\n"
        f"Category: {category_name}\n"
        f"Scheduled Time: {formatted_time}"
    )

    html_content = f"""
    <html>
    <body style="font-family: Arial; background:#f4f6f8; padding:20px;">
        <div style="max-width:500px; margin:auto; background:white; border-radius:10px;
                    padding:20px; border:1px solid #e5e7eb;">
            <h2 style="color:#4f46e5; margin-top:0;">&#x1F514; Reminder</h2>
            <p><strong>Title:</strong> {title}</p>
            <p><strong>Purpose:</strong> {purpose}</p>
            <p><strong>Category:</strong> {category_name}</p>
            <p><strong>Scheduled Time:</strong>
               <span style="color:#059669; font-weight:bold;">{formatted_time}</span>
            </p>
            <hr style="margin:20px 0;">
            <p style="font-size:12px; color:#6b7280; text-align:center;">
                Automated Reminder System
            </p>
        </div>
    </body>
    </html>
    """

    try:
        msg = EmailMultiAlternatives(
            subject,
            text_content,
            settings.DEFAULT_FROM_EMAIL,
            to_emails,
            cc=cc_emails,
        )
        msg.attach_alternative(html_content, "text/html")

        # BUG FIX: Check the return value of send().  It returns the number of
        # successfully delivered messages.  A return value of 0 means nothing
        # was sent (possible when a backend has fail_silently=True upstream)
        # — treat that as a failure so the ActivityLog is accurate.
        sent = msg.send()
        if not sent:
            raise RuntimeError(
                f"email.send() returned 0 for Reminder ID {reminder.id} "
                f"— message was not delivered"
            )

        _log_activity(
            reminder,
            status="success",
            description=f"Reminder sent: {reminder.title}",
        )
        # BUG FIX: Use logger.info (not error_logger) for success, consistent
        # with the rest of the scheduler logging convention
        logger.info(f"Email sent for Reminder ID {reminder.id} | {title}")

    except Exception as e:
        # BUG FIX: logger.exception() captures the full traceback; the original
        # error_logger.error(str(e)) only logged the message string, making
        # stack traces invisible in production logs.
        error_logger.exception(f"Email send failed for Reminder ID {reminder.id}")

        _log_activity(
            reminder,
            status="error",
            description=f"Failed: {reminder.title} — {str(e)}",
        )

        # BUG FIX: bare `raise` preserves the original traceback.
        # `raise e` resets it to this line, hiding where the error originated.
        raise
import os
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


def _log_activity(reminder, is_success, details):
    """
    Write an ActivityLog row, swallowing any DB errors so a logging failure
    never masks the real exception.
    """
    # FIXED: Combine into the 'action' field, as 'status' and 'description' don't exist
    prefix = "Email Sent:" if is_success else "Email Failed:"
    full_action = f"{prefix} {details}"
    
    # FIXED: Enforce the 255 max_length limit of the action field to prevent DB crashes
    safe_action = (full_action[:252] + '...') if len(full_action) > 255 else full_action

    try:
        ActivityLog.objects.create(
            user=reminder.user,
            action=safe_action,
            # ip_address is left as None since this is a system-generated action
        )
    except Exception:
        error_logger.exception(
            f"ActivityLog write failed for Reminder ID {reminder.id} "
            f"— original email outcome is unaffected"
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

        if reminder.attachment and reminder.attachment.name:
            file_path = os.path.join(settings.MEDIA_ROOT, reminder.attachment.name)
            if os.path.exists(file_path):
                msg.attach_file(file_path)
            else:
                error_logger.warning(
                    f"Attachment missing on disk for Reminder ID {reminder.id}. "
                    f"Expected path: {file_path}"
                )

        sent = msg.send()
        if not sent:
            raise RuntimeError(
                f"email.send() returned 0 for Reminder ID {reminder.id} "
                f"— message was not delivered"
            )

        _log_activity(
            reminder,
            is_success=True,
            details=reminder.title
        )
        
        logger.info(f"Email sent for Reminder ID {reminder.id} | {title}")

    except Exception as e:
        error_logger.exception(f"Email send failed for Reminder ID {reminder.id}")

        _log_activity(
            reminder,
            is_success=False,
            details=f"[{reminder.title}] {str(e)}"
        )

        raise
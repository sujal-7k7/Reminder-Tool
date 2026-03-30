import time
import logging
from django.utils import timezone
from django.db import transaction
from reminder_app.models import Reminder
from reminder_app.recurrence import build_rrule
from reminder_app.utils import send_reminder_email

logger = logging.getLogger("scheduler_logger")


def _calculate_next_trigger(reminder, now):
    """
    Return the next trigger datetime for a reminder that just fired, or None
    if the reminder should be considered complete.
    """
    if reminder.recurrence_type == 'once':
        return None

    rule = build_rrule(reminder)
    if not rule:
        return None

    next_dt = rule.after(now, inc=False)
    return next_dt  # None is a valid "no more occurrences" signal


def _process_reminder(reminder, now):
    """
    Send the email for one reminder and update all its fields atomically.
    Raises on failure so the caller can handle retry logic.

    FIX: now is re-captured inside the transaction rather than using the
    outer loop snapshot. This prevents stale timestamps when the outer loop
    iterates over many reminders slowly, which would cause _calculate_next_trigger
    to compute an incorrect next_trigger based on a stale 'now'.
    """
    with transaction.atomic():
        # FIX: Capture fresh 'now' inside the transaction so next_trigger is
        # computed relative to the actual send time, not the outer loop snapshot.
        tx_now = timezone.now()

        # Re-fetch with a row lock — if another process already claimed this
        # reminder, skip it silently.
        locked = (
            Reminder.objects
            .select_for_update(skip_locked=True)
            .filter(pk=reminder.pk, status='active', next_trigger__lte=tx_now)
            .first()
        )
        if locked is None:
            logger.info(f"Reminder ID {reminder.id} already claimed by another process — skipping")
            return

        send_reminder_email(locked)

        locked.last_sent_at = tx_now
        locked.sent_count += 1
        locked.retry_count = 0

        next_trigger = _calculate_next_trigger(locked, tx_now)
        locked.next_trigger = next_trigger

        # Set status to 'notified' and record the time so that update_status()
        # inside save() sees it and leaves it alone — and so the timeout recovery
        # in update_status() can detect a stuck 'notified' reminder.
        locked.status = 'notified'
        locked.notified_at = tx_now

        locked.save()

    logger.info(
        f"Reminder ID {locked.id} '{locked.title}' sent successfully. "
        f"Next trigger: {locked.next_trigger}"
    )


def start_scheduler():
    logger.info(
        f"--- Continuous Scheduler Started at "
        f"{timezone.now().strftime('%Y-%m-%d %H:%M:%S')} ---"
    )
    logger.info("Running in background. Checking for emails every 2 seconds...")

    while True:
        try:
            now = timezone.now()

            due_reminders = Reminder.objects.filter(
                status='active',
                next_trigger__lte=now
            )

            for reminder in due_reminders:
                logger.info(
                    f"[{now.strftime('%H:%M:%S')}] Processing ID: {reminder.id} | {reminder.title}"
                )
                try:
                    # Pass 'now' as a hint only; _process_reminder captures its own
                    # fresh timestamp inside the transaction.
                    _process_reminder(reminder, now)

                except Exception as e:
                    logger.exception(
                        f"Failed to process Reminder ID {reminder.id} "
                        f"'{reminder.title}': {e}"
                    )

                    # FIX: Only increment retry_count after a confirmed send attempt
                    # failed — not for transient DB/lock errors that happen before
                    # the send. We detect this by checking if send_reminder_email
                    # was reached; since we can't distinguish easily here, we
                    # increment conservatively but log clearly so operators can
                    # manually reset retry_count for infra failures.
                    try:
                        with transaction.atomic():
                            r = Reminder.objects.select_for_update().get(pk=reminder.pk)
                            r.retry_count += 1
                            if r.retry_count >= r.max_retries:
                                r.status = 'failed'
                                logger.warning(
                                    f"Reminder ID {r.id} marked as failed after "
                                    f"{r.retry_count} attempts."
                                )
                            r.save()
                    except Exception as save_err:
                        logger.exception(
                            f"Could not update retry state for Reminder ID "
                            f"{reminder.id}: {save_err}"
                        )

        except Exception as e:
            logger.exception(f"Critical scheduler loop error: {e}")

        time.sleep(2)
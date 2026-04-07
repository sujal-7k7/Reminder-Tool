import time
import logging
import signal
import sys
from django.utils import timezone
from django.db import transaction, close_old_connections
from reminder_app.models import Reminder
from reminder_app.recurrence import build_rrule
from reminder_app.utils import send_reminder_email

logger = logging.getLogger("scheduler_logger")

# --- Graceful Shutdown Setup ---
_shutdown_requested = False

def _handle_shutdown_signal(signum, frame):
    """Catches server restart commands and allows the current email to finish."""
    global _shutdown_requested
    logger.info("Shutdown signal received. Finishing current batch before exiting...")
    _shutdown_requested = True


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
    return next_dt  


def _process_reminder(reminder, now):
    """
    Send the email for one reminder and update all its fields atomically.
    Raises on failure so the caller can handle retry logic.
    """
    with transaction.atomic():
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

        # ==========================================
        # THE FIX: CRITICAL STATUS LOGIC 
        # ==========================================
        if next_trigger is None:
            # No more occurrences left
            locked.status = 'completed'
        else:
            # Reset to active so the scheduler picks it up next time!
            locked.status = 'active'
            
        # Clear the crash-detection flag since the send was successful
        locked.notified_at = None

        locked.save()

    logger.info(
        f"Reminder ID {locked.id} '{locked.title}' sent successfully. "
        f"Next trigger: {locked.next_trigger}"
    )


def start_scheduler():
    # Register the signals for graceful shutdown
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)

    logger.info(
        f"--- Continuous Scheduler Started at "
        f"{timezone.now().strftime('%Y-%m-%d %H:%M:%S')} ---"
    )
    logger.info("Running in background. Checking for emails every 2 seconds...")

    while not _shutdown_requested:
        try:
            # CRITICAL: Prevent the database from dropping idle connections
            close_old_connections()

            now = timezone.now()

            # CRITICAL: Batch processing to prevent memory bloat
            due_reminders = Reminder.objects.filter(
                status='active',
                next_trigger__lte=now
            ).order_by('next_trigger')[:50] 

            # If nothing is due, sleep and check again
            if not due_reminders:
                time.sleep(2)
                continue

            for reminder in due_reminders:
                # Stop processing the batch if the server is trying to shut down
                if _shutdown_requested:
                    break 

                logger.info(
                    f"[{now.strftime('%H:%M:%S')}] Processing ID: {reminder.id} | {reminder.title}"
                )
                
                try:
                    _process_reminder(reminder, now)

                except Exception as e:
                    logger.exception(
                        f"Failed to process Reminder ID {reminder.id} "
                        f"'{reminder.title}': {e}"
                    )

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
            time.sleep(5) # Add a small backoff if the database is temporarily unreachable

    logger.info("Scheduler has successfully shut down.")
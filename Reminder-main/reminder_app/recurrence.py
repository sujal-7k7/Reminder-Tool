from datetime import datetime, time as dt_time
from django.utils import timezone
from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY, YEARLY, HOURLY
from dateutil.rrule import MO, TU, WE, TH, FR, SA, SU
import logging

error_logger = logging.getLogger("error_logger")

DAY_MAP = {'0': MO, '1': TU, '2': WE, '3': TH, '4': FR, '5': SA, '6': SU}


def make_aware_safe(dt):
    """Return an aware datetime, leaving already-aware datetimes untouched."""
    if dt is None:
        return None
    if timezone.is_aware(dt):
        return dt
    return timezone.make_aware(dt)


def _parse_single_weekday(value):
    """
    Safely extract a single DAY_MAP entry from a field that should hold one
    weekday key (e.g. monthly/yearly nth_weekday mode).

    Accepts "0", "0,1" (takes first), or None/empty — returns None on failure.
    """
    if not value:
        return None
    key = value.split(',')[0].strip()
    return DAY_MAP.get(key)


def build_rrule(reminder):
    """
    Build and return a dateutil rrule for the given Reminder instance.
    Returns None for one-time reminders or if construction fails.
    """
    if reminder.recurrence_type == 'once':
        return None

    valid_types = {'daily', 'weekly', 'monthly', 'yearly'}
    if reminder.recurrence_type not in valid_types:
        error_logger.error(
            f"build_rrule: unknown recurrence_type '{reminder.recurrence_type}' "
            f"on Reminder ID {reminder.id} — returning None"
        )
        return None

    dtstart = make_aware_safe(datetime.combine(reminder.start_date, reminder.time))
    kwargs = {'dtstart': dtstart, 'interval': reminder.interval or 1}

    # ── End condition ──────────────────────────────────────────────────────────

    if reminder.end_date:
        end_dt = datetime.combine(reminder.end_date, dt_time(23, 59, 59))
        kwargs['until'] = make_aware_safe(end_dt)

    # FIX: Guard against occurrence_count=0 reaching rrule(count=0).
    # dateutil with count=0 returns an empty sequence — rule.after() silently
    # returns None and the reminder completes immediately without ever firing.
    # Only set count when the value is a positive integer.
    if reminder.occurrence_count is not None and reminder.occurrence_count > 0:
        kwargs['count'] = reminder.occurrence_count

    # ── Frequency-specific config ──────────────────────────────────────────────

    req_type = reminder.recurrence_type

    if req_type == 'daily':
        if reminder.hour_interval:
            kwargs['freq'] = HOURLY
            kwargs['interval'] = reminder.hour_interval
        else:
            kwargs['freq'] = DAILY

        if reminder.daily_mode == 'weekday':
            # FIX: Comment updated to accurately reflect the code.
            # Code applies Mon–Fri (MO, TU, WE, TH, FR) only.
            # The previous comment incorrectly said "Mon–Sat" — this was a
            # documentation error; the template label should read "Mon–Fri".
            kwargs['byweekday'] = (MO, TU, WE, TH, FR)

    elif req_type == 'weekly':
        kwargs['freq'] = WEEKLY
        if reminder.by_weekday:
            days = [DAY_MAP[d] for d in reminder.by_weekday.split(',') if d in DAY_MAP]
            if days:
                kwargs['byweekday'] = days

    elif req_type == 'monthly':
        kwargs['freq'] = MONTHLY
        if reminder.monthly_mode == 'day_of_month' and reminder.by_monthday:
            kwargs['bymonthday'] = reminder.by_monthday
        elif reminder.monthly_mode == 'nth_weekday':
            if reminder.by_setpos is not None:
                kwargs['bysetpos'] = reminder.by_setpos
            weekday = _parse_single_weekday(reminder.by_weekday)
            if weekday is not None:
                kwargs['byweekday'] = weekday

    elif req_type == 'yearly':
        kwargs['freq'] = YEARLY
        if reminder.by_month:
            kwargs['bymonth'] = reminder.by_month
        if reminder.yearly_mode == 'specific_date' and reminder.by_monthday:
            kwargs['bymonthday'] = reminder.by_monthday
        elif reminder.yearly_mode == 'nth_weekday':
            if reminder.by_setpos is not None:
                kwargs['bysetpos'] = reminder.by_setpos
            weekday = _parse_single_weekday(reminder.by_weekday)
            if weekday is not None:
                kwargs['byweekday'] = weekday

    try:
        return rrule(**kwargs)
    except Exception as e:
        error_logger.error(f"RRule build failed for Reminder ID {reminder.id}: {str(e)}")
        return None
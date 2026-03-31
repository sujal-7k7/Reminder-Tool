from django import forms
from django.utils import timezone
from .models import Reminder


class ReminderForm(forms.ModelForm):
    # WEEKDAY CHOICES
    WEEKDAY_CHOICES = [
        ('0', 'Mon'), ('1', 'Tue'), ('2', 'Wed'),
        ('3', 'Thu'), ('4', 'Fri'), ('5', 'Sat'), ('6', 'Sun'),
    ]

    weekdays = forms.MultipleChoiceField(
        choices=WEEKDAY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False
    )

    class Meta:
        model = Reminder
        fields = [
            "title",
            "subject",
            "purpose",
            "category",
            "attachment",  # <-- NEW: Added attachment field here
            "email_to",
            "email_cc",
            "start_date",
            "time",
            "recurrence_type",
            "interval",
            "daily_mode",
            "hour_interval",
            "by_weekday",
            "monthly_mode",
            "by_monthday",
            "by_setpos",
            "yearly_mode",
            "by_month",
            "range_type",
            "end_date",
            "occurrence_count",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['interval'].required = False
        self.fields['time'].required = False
        self.fields['start_date'].required = False
        self.fields['range_type'].required = False
        self.fields['monthly_mode'].required = False
        self.fields['yearly_mode'].required = False
        # Ensure attachment is not strictly required by the form
        self.fields['attachment'].required = False 

        # Restore weekly_days checkboxes when editing an existing instance
        if self.instance.pk and self.instance.by_weekday and self.instance.recurrence_type == 'weekly':
            self.initial["weekdays"] = self.instance.by_weekday.split(",")

    # ------------------------------------------------------------------
    # FIELD-LEVEL VALIDATORS
    # ------------------------------------------------------------------

    def clean_start_date(self):
        """Ensure start_date is provided."""
        start_date = self.cleaned_data.get("start_date")
        if not start_date:
            raise forms.ValidationError("Start date is required.")
        return start_date

    def clean_time(self):
        """Ensure time is provided."""
        time_val = self.cleaned_data.get("time")
        if not time_val:
            raise forms.ValidationError("Start time is required.")
        return time_val

    def clean_interval(self):
        """
        For 'once' recurrence, interval is never sent — default to 1 silently.
        For all other types, validate range 1–365.
        FIX: Use self.cleaned_data.get() instead of self.data.get() so that
             Django's choice validation has already run and invalid values
             are caught before reaching this method.
        """
        interval = self.cleaned_data.get("interval")
        # FIX: Read from cleaned_data (already validated) rather than raw self.data
        recurrence_type = self.cleaned_data.get("recurrence_type", "once")

        if recurrence_type == "once":
            return 1

        if interval is None:
            raise forms.ValidationError("Interval is required.")
        if interval < 1:
            raise forms.ValidationError("Interval must be at least 1.")
        if interval > 365:
            raise forms.ValidationError("Interval cannot exceed 365.")
        return interval

    def clean_by_monthday(self):
        """Day-of-month must be 1–31."""
        by_monthday = self.cleaned_data.get("by_monthday")
        if by_monthday is not None:
            if by_monthday < 1 or by_monthday > 31:
                raise forms.ValidationError("Day of month must be between 1 and 31.")
        return by_monthday

    def clean_by_setpos(self):
        """Validate by_setpos is one of the allowed positional values."""
        by_setpos = self.cleaned_data.get("by_setpos")
        if by_setpos is not None:
            if by_setpos not in (1, 2, 3, 4, -1):
                raise forms.ValidationError(
                    "Position must be First (1), Second (2), Third (3), Fourth (4), or Last (-1)."
                )
        return by_setpos

    def clean_hour_interval(self):
        """Validate hour_interval range. Presence alone signals hourly is enabled."""
        hour_interval = self.cleaned_data.get("hour_interval")
        if hour_interval is not None:
            if hour_interval < 1 or hour_interval > 23:
                raise forms.ValidationError("Hour interval must be between 1 and 23.")
        return hour_interval

    def clean_occurrence_count(self):
        """Occurrence count must be 1–999."""
        occ = self.cleaned_data.get("occurrence_count")
        if occ is not None:
            if occ < 1:
                raise forms.ValidationError("Occurrences must be at least 1.")
            if occ > 999:
                raise forms.ValidationError("Occurrences cannot exceed 999.")
        return occ

    # ------------------------------------------------------------------
    # CROSS-FIELD VALIDATION
    # ------------------------------------------------------------------

    def clean(self):
        cleaned_data = super().clean()
        recurrence_type = cleaned_data.get("recurrence_type")
        start_date = cleaned_data.get("start_date")
        time_val = cleaned_data.get("time")

        # Past-check combines start_date + time so a same-day past time is also caught.
        # FIX: Run past-date check for both create AND edit, using instance.pk to
        #      differentiate. For edits, only raise if the start_date/time actually changed.
        if start_date:
            if time_val:
                from datetime import datetime as _dt
                naive_start = _dt.combine(start_date, time_val)
                aware_start = timezone.make_aware(naive_start)
                # For new reminders: always check past
                # For edits: only check if the date/time actually changed
                if not self.instance.pk:
                    if aware_start <= timezone.now():
                        self.add_error("start_date", "Start date and time cannot be in the past.")
                else:
                    from datetime import datetime as _dt2
                    original_start = _dt2.combine(self.instance.start_date, self.instance.time)
                    original_aware = timezone.make_aware(original_start)
                    if aware_start != original_aware and aware_start <= timezone.now():
                        self.add_error("start_date", "New start date and time cannot be in the past.")
            else:
                if not self.instance.pk and start_date < timezone.localdate():
                    self.add_error("start_date", "Start date cannot be in the past.")

        # One-time reminders need no recurrence validation
        if recurrence_type == "once":
            return cleaned_data

        interval = cleaned_data.get("interval")
        if not interval or interval < 1:
            self.add_error("interval", f"A valid interval is required for {recurrence_type} reminders.")

        # WEEKLY
        if recurrence_type == "weekly":
            if not cleaned_data.get("weekdays"):
                self.add_error("weekdays", "Select at least one weekday.")

        # MONTHLY
        if recurrence_type == "monthly":
            monthly_mode = cleaned_data.get("monthly_mode")
            if monthly_mode == "day_of_month":
                by_monthday = cleaned_data.get("by_monthday")
                if by_monthday is None:
                    self.add_error("by_monthday", "Day of month is required.")
            elif monthly_mode == "nth_weekday":
                if cleaned_data.get("by_setpos") is None or not cleaned_data.get("by_weekday"):
                    self.add_error("by_setpos", "Select a week position and weekday.")

        # YEARLY
        if recurrence_type == "yearly":
            yearly_mode = cleaned_data.get("yearly_mode")
            if yearly_mode == "specific_date":
                by_month = cleaned_data.get("by_month")
                by_monthday = cleaned_data.get("by_monthday")
                if by_month is None or by_monthday is None:
                    self.add_error("by_month", "Month and day are required for yearly reminders.")
            elif yearly_mode == "nth_weekday":
                if (
                    cleaned_data.get("by_month") is None
                    or cleaned_data.get("by_setpos") is None
                    or not cleaned_data.get("by_weekday")
                ):
                    self.add_error("by_setpos", "Complete all yearly positional fields.")

        # END CONDITION — exactly one of end_date / occurrence_count must be set
        end_date = cleaned_data.get("end_date")
        occurrence_count = cleaned_data.get("occurrence_count")

        has_end_date = end_date is not None
        has_occurrence = occurrence_count is not None

        if has_end_date and has_occurrence:
            self.add_error(
                "end_date",
                "Choose only one end condition: an End Date OR a number of occurrences, not both.",
            )
        elif not has_end_date and not has_occurrence:
            self.add_error(
                "range_type",
                "For recurring reminders, choose one end condition: an End Date OR a number of occurrences.",
            )

        # End date must be strictly after start date
        if has_end_date and start_date and end_date <= start_date:
            self.add_error("end_date", "End date must be strictly after the start date.")

        return cleaned_data

    # ------------------------------------------------------------------
    # SAVE — clean up stale recurrence fields before writing to DB
    # ------------------------------------------------------------------

    def save(self, commit=True):
        instance = super().save(commit=False)
        weekdays = self.cleaned_data.get("weekdays")

        if instance.recurrence_type == 'weekly':
            instance.by_weekday = ",".join(weekdays) if weekdays else ""
            instance.daily_mode = ""
            instance.hour_interval = None
            instance.monthly_mode = ""
            instance.by_monthday = None
            instance.by_setpos = None
            instance.by_month = None
            instance.yearly_mode = ""

        elif instance.recurrence_type == 'daily':
            instance.by_weekday = ""
            instance.monthly_mode = ""
            instance.by_monthday = None
            instance.by_setpos = None
            instance.by_month = None
            instance.yearly_mode = ""
            if instance.daily_mode == "weekday":
                instance.interval = 1

        elif instance.recurrence_type == 'monthly':
            instance.daily_mode = ""
            instance.hour_interval = None
            instance.yearly_mode = ""
            instance.by_month = None
            if instance.monthly_mode == "day_of_month":
                instance.by_weekday = ""
                instance.by_setpos = None
            elif instance.monthly_mode == "nth_weekday":
                instance.by_monthday = None

        elif instance.recurrence_type == 'yearly':
            instance.daily_mode = ""
            instance.hour_interval = None
            instance.monthly_mode = ""
            if instance.yearly_mode == "specific_date":
                instance.by_weekday = ""
                instance.by_setpos = None
            elif instance.yearly_mode == "nth_weekday":
                instance.by_monthday = None

        else:
            # once — clear everything recurrence-related
            instance.by_weekday = ""
            instance.daily_mode = ""
            instance.hour_interval = None
            instance.monthly_mode = ""
            instance.by_monthday = None
            instance.by_setpos = None
            instance.by_month = None
            instance.yearly_mode = ""
            instance.interval = 1
            instance.end_date = None
            instance.occurrence_count = None
            instance.range_type = ""

        if commit:
            instance.save()
        return instance
    
    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')
        if attachment:
            # 1. Extension Check
            allowed_exts = ['pdf', 'txt', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx']
            import os
            ext = os.path.splitext(attachment.name)[1][1:].lower()
            
            if ext not in allowed_exts:
                raise forms.ValidationError(f"Allowed types: {', '.join(allowed_exts)}")
            
            # 2. Email-Safe Size Check: 20MB
            # 20 * 1024 * 1024 = 20,971,520 bytes
            if attachment.size > 20 * 1024 * 1024:
                raise forms.ValidationError("File is too large for email delivery. Please keep it under 20MB.")
                
        return attachment
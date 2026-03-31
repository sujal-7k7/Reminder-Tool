from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
import os
from .models import Reminder

class ReminderForm(forms.ModelForm):
    class Meta:
        model = Reminder
        # We define the fields that users are allowed to submit
        fields = [
            'title', 'subject', 'purpose', 'category', 'attachment',
            'email_to', 'email_cc', 'start_date', 'time',
            'recurrence_type', 'interval', 'daily_mode', 'hour_interval',
            'by_weekday', 'monthly_mode', 'by_monthday', 'by_setpos',
            'yearly_mode', 'by_month', 'range_type', 'end_date', 'occurrence_count'
        ]

    def clean_attachment(self):
        """Backend validation for file size and extensions."""
        file = self.cleaned_data.get('attachment')
        if file:
            # 1. Enforce 20MB limit on the backend
            max_size = 20 * 1024 * 1024
            if file.size > max_size:
                raise ValidationError("File size must be under 20MB.")

            # 2. Block dangerous file types (.exe, .sh, .py, etc.)
            ext = os.path.splitext(file.name)[1].lower()
            valid_extensions = ['.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']
            if ext not in valid_extensions:
                raise ValidationError("Unsupported file type. Allowed: PDF, TXT, Word, Excel, PPT.")
        return file

    def _clean_email_list(self, email_string):
        """Helper to sanitize and validate semicolon-separated emails."""
        if not email_string:
            return ""
        
        # Split by semicolon and remove blank spaces
        emails = [e.strip() for e in email_string.split(';') if e.strip()]
        
        if not emails:
            return ""

        # Validate each individual email against standard email formats
        for email in emails:
            try:
                validate_email(email)
            except ValidationError:
                raise ValidationError(f"Invalid email address found: '{email}'")
        
        # Rejoin with clean semicolons to store neatly in the database
        return "; ".join(emails)

    def clean_email_to(self):
        email_to = self.cleaned_data.get('email_to')
        if not email_to:
            raise ValidationError("At least one recipient email is required.")
        return self._clean_email_list(email_to)

    def clean_email_cc(self):
        email_cc = self.cleaned_data.get('email_cc')
        return self._clean_email_list(email_cc)
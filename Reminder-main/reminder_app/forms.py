from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
import os
import mimetypes
from .models import Reminder

class ReminderForm(forms.ModelForm):
    class Meta:
        model = Reminder
        fields = [
            'title', 'subject', 'purpose', 'category', 'attachment',
            'email_to', 'email_cc', 'start_date', 'time',
            'recurrence_type', 'interval', 'daily_mode', 'hour_interval',
            'by_weekday', 'monthly_mode', 'by_monthday', 'by_setpos',
            'yearly_mode', 'by_month', 'range_type', 'end_date', 'occurrence_count'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 1. Conditionally Required Fields 
        self.fields['end_date'].required         = False
        self.fields['occurrence_count'].required = False
        self.fields['range_type'].required       = False

        # 2. Inherently Optional Fields
        self.fields['purpose'].required       = False
        self.fields['category'].required      = False
        self.fields['attachment'].required    = False
        self.fields['email_cc'].required      = False
        self.fields['daily_mode'].required    = False
        self.fields['hour_interval'].required = False
        self.fields['by_weekday'].required    = False
        self.fields['monthly_mode'].required  = False
        self.fields['by_monthday'].required   = False
        self.fields['by_setpos'].required     = False
        self.fields['yearly_mode'].required   = False
        self.fields['by_month'].required      = False
        self.fields['interval'].required      = False

    def clean_attachment(self):
        """Security: Enforces file size limits and strict MIME whitelists."""
        file = self.cleaned_data.get('attachment')
        if file:
            max_size = 20 * 1024 * 1024  # 20MB Limit
            if file.size > max_size:
                raise ValidationError("File size must be under 20MB.")
            
            ext = os.path.splitext(file.name)[1].lower()
            valid_extensions = ['.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']
            
            if ext not in valid_extensions:
                raise ValidationError("Unsupported file extension. Allowed: PDF, TXT, Word, Excel, PPT.")
                
            # STRICT FIX: Explicitly map out the exact allowed MIME types
            content_type = getattr(file, 'content_type', '')
            allowed_mimes = [
                'application/pdf', 
                'text/plain', 
                'application/msword', 
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/vnd.ms-excel', 
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'application/vnd.ms-powerpoint', 
                'application/vnd.openxmlformats-officedocument.presentationml.presentation'
            ]
            
            if content_type not in allowed_mimes:
                raise ValidationError("Invalid or potentially malicious file content type detected.")
                
        return file

    def _clean_email_list(self, email_string):
        """Utility: Sanitizes and validates semicolon-separated and comma-separated emails."""
        if not email_string:
            return ""
        
        # FIX: Replace any commas with semicolons to standardize the string
        email_string = email_string.replace(',', ';')
        
        # Split strictly by semicolon and remove empty spaces
        emails = [e.strip() for e in email_string.split(';') if e.strip()]
        if not emails:
            return ""
            
        for email in emails:
            try:
                validate_email(email)
            except ValidationError:
                raise ValidationError(f"Invalid email address found: '{email}'")
                
        return "; ".join(emails)

    def clean_email_to(self):
        email_to = self.cleaned_data.get('email_to')
        if not email_to:
            raise ValidationError("At least one recipient email is required.")
        return self._clean_email_list(email_to)

    def clean_email_cc(self):
        email_cc = self.cleaned_data.get('email_cc')
        return self._clean_email_list(email_cc)

    def clean(self):
        """
        Master cross-field validation. 
        Secures the database against malicious or glitchy frontend payloads.
        """
        cleaned = super().clean()
        
        recurrence_type  = cleaned.get('recurrence_type')
        range_type       = cleaned.get('range_type')
        end_date         = cleaned.get('end_date')
        occurrence_count = cleaned.get('occurrence_count')
        start_date       = cleaned.get('start_date')
        interval         = cleaned.get('interval')

        # --- VALIDATIONS FOR RECURRING TASKS ---
        if recurrence_type and recurrence_type != 'once':
            
            # A. Interval bounds checking (Safe type checking)
            if interval is not None:
                try:
                    if int(interval) < 1:
                        self.add_error('interval', "Interval must be at least 1.")
                except ValueError:
                    self.add_error('interval', "Interval must be a valid number.")

            # B. Specific Requirements
            if recurrence_type == 'weekly' and not cleaned.get('by_weekday'):
                raise ValidationError("You must select at least one day for weekly recurrence.")
            
            if recurrence_type == 'daily' and cleaned.get('daily_mode') == 'interval' and not interval:
                 raise ValidationError("You must provide a day interval for daily recurrence.")

            # C. End-Range Logic
            if not range_type:
                raise ValidationError("Please select an End Range for your recurring reminder.")

            if range_type == 'end_by':
                cleaned['occurrence_count'] = None  # Wipe conflicting data 
                if not end_date:
                    self.add_error('end_date', "Please select a specific End Date.")
                elif start_date and end_date < start_date:
                    self.add_error('end_date', "End Date cannot be before the Start Date.")

            elif range_type == 'end_after':
                cleaned['end_date'] = None  # Wipe conflicting data        
                if not occurrence_count:
                    self.add_error('occurrence_count', "Please enter a valid number of occurrences.")
                else:
                    try:
                        if int(occurrence_count) < 1:
                            self.add_error('occurrence_count', "Occurrences must be at least 1.")
                    except ValueError:
                        self.add_error('occurrence_count', "Occurrences must be a valid number.")

        # --- DATA SANITIZATION FOR ONE-TIME TASKS ---
        else:
            cleaned['end_date']         = None
            cleaned['occurrence_count'] = None
            cleaned['range_type']       = ''
            cleaned['interval']         = 1
            
            cleaned['by_weekday']       = ''
            cleaned['daily_mode']       = ''
            cleaned['hour_interval']    = None
            cleaned['monthly_mode']     = ''
            cleaned['yearly_mode']      = ''
            cleaned['by_monthday']      = None
            cleaned['by_setpos']        = None
            cleaned['by_month']         = None
            
        return cleaned
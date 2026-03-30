import os
import django

# NOTE: Make sure "reminder_project.settings" exactly matches your actual project folder name
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "reminder_project.settings")
django.setup()

from reminder_app.scheduler import start_scheduler

if __name__ == "__main__":
    start_scheduler()
from django.core.management.base import BaseCommand
from reminder_app.scheduler import check_due_reminders


class Command(BaseCommand):
    help = "Check and send due reminders"

    def handle(self, *args, **kwargs):
        check_due_reminders()
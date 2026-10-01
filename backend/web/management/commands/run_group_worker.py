from django.core.management.base import BaseCommand

from web.views.group_worker import run_worker


class Command(BaseCommand):
    help = 'Process durable AI group reply tasks independently of browser connections.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process one queued reply and exit.')

    def handle(self, *args, **options):
        self.stdout.write('AI group worker started. Press Ctrl+C to stop.')
        try:
            run_worker(once=options['once'])
        except KeyboardInterrupt:
            self.stdout.write('AI group worker stopped.')

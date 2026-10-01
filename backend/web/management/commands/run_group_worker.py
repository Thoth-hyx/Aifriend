import time

from django.core.management.base import BaseCommand

from web.views.group_worker import process_next, recover_stale


class Command(BaseCommand):
    help = 'Process durable AI group reply tasks independently of browser connections.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process one queued reply and exit.')

    def handle(self, *args, **options):
        self.stdout.write('AI group worker started. Press Ctrl+C to stop.')
        # ponytail: one worker processes replies serially; add workers when queue latency matters.
        try:
            while True:
                recover_stale()
                processed = process_next()
                if options['once']:
                    break
                if not processed:
                    time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write('AI group worker stopped.')

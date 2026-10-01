from threading import Event, Thread

from django.contrib.staticfiles.management.commands.runserver import Command as RunserverCommand

from web.views.group_worker import run_worker


class Command(RunserverCommand):
    def inner_run(self, *args, **options):
        self.worker_stop = Event()
        try:
            return super().inner_run(*args, **options)
        finally:
            self.worker_stop.set()

    def on_bind(self, server_port):
        super().on_bind(server_port)
        # Start only in the serving process, after checks and a successful port bind.
        Thread(
            target=run_worker, kwargs={'stop_event': self.worker_stop},
            name='ai-group-worker', daemon=True,
        ).start()
        self.stdout.write('AI group worker started automatically.')

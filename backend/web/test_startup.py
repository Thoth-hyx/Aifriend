from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.management import get_commands
from django.test import RequestFactory, SimpleTestCase, override_settings

from web.management.commands.runserver import Command
from web.views.group_worker import run_worker
from web.views.index import index


class StartupTests(SimpleTestCase):
    def test_runserver_starts_worker_at_bind_and_stops_on_exit(self):
        self.assertEqual(get_commands()['runserver'], 'web')
        command = Command()
        with patch('web.management.commands.runserver.Thread') as thread, patch(
            'web.management.commands.runserver.RunserverCommand.on_bind',
        ), patch(
            'web.management.commands.runserver.RunserverCommand.inner_run',
            side_effect=lambda *args, **kwargs: command.on_bind(8000),
        ):
            command.inner_run(use_reloader=True)
        thread.assert_called_once_with(
            target=run_worker, kwargs={'stop_event': command.worker_stop},
            name='ai-group-worker', daemon=True,
        )
        thread.return_value.start.assert_called_once()
        self.assertTrue(command.worker_stop.is_set())
        parser = command.create_parser('manage.py', 'runserver')
        self.assertFalse(parser.parse_args(['--noreload', '--nostatic']).use_reloader)
        with patch('web.management.commands.runserver.Thread') as thread, patch(
            'web.management.commands.runserver.RunserverCommand.inner_run',
            side_effect=SystemExit,
        ):
            with self.assertRaises(SystemExit):
                command.inner_run()
        thread.assert_not_called()
        self.assertTrue(command.worker_stop.is_set())

    def test_worker_survives_iteration_error_and_stops(self):
        stop = Mock()
        stop.is_set.side_effect = [False, False, True]
        with patch('web.views.group_worker.recover_stale', side_effect=[RuntimeError('DB busy'), None]), patch(
            'web.views.group_worker.process_next', return_value=False,
        ) as process, patch('web.views.group_worker.logger') as logger, patch(
            'web.views.group_worker.close_old_connections',
        ) as close:
            run_worker(stop_event=stop)
        process.assert_called_once()
        logger.exception.assert_called_once()
        self.assertEqual(stop.wait.call_count, 2)
        close.assert_called_once()

    def test_django_serves_latest_built_entry_for_spa_routes(self):
        with TemporaryDirectory(dir=settings.BASE_DIR) as directory:
            built_index = Path(directory) / 'static/frontend/index.html'
            built_index.parent.mkdir(parents=True)
            built_index.write_text('<script src="/static/frontend/assets/latest.js"></script>', encoding='utf-8')
            with override_settings(BASE_DIR=Path(directory)):
                response = index(RequestFactory().get('/group/1/'))
                try:
                    self.assertEqual(response['Content-Type'], 'text/html')
                    self.assertIn(b'/static/frontend/assets/latest.js', b''.join(response.streaming_content))
                finally:
                    response.close()

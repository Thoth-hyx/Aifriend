"""Run with python test/run.py; --live explicitly enables the configured LLM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from contextlib import ExitStack
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from evaluation import check_context, grade_answer, load_dataset, summarize, write_report

ROOT = Path(__file__).resolve().parents[1]


def temporary_workspace():
    directory = ROOT / '.tmp'
    directory.mkdir(exist_ok=True)
    return TemporaryDirectory(prefix='aifriends-eval-', dir=directory)


def configure_django(directory):
    sys.path.insert(0, str(ROOT / 'backend'))
    os.chdir(ROOT / 'backend')  # Existing knowledge-base paths are relative to backend.
    os.environ['DJANGO_SETTINGS_MODULE'] = 'backend.settings'
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    os.environ['LANGSMITH_TRACING'] = 'false'
    import django
    from django.conf import settings
    settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(Path(directory) / 'unused.sqlite3')}}
    django.setup()


def prepare_conversation(case, system_prompt):
    from django.contrib.auth.models import User
    from web.models.user import UserProfile
    from web.models.character import Character
    from web.models.friend import Friend, SystemPrompt
    from web.models.group import ChatGroup, GroupMessage
    from web.views.group_worker import create_inputs

    user = User.objects.create(username='评测用户')
    profile = UserProfile.objects.create(user=user)
    character = Character.objects.create(author=profile, name=case['character_name'],
        profile=case['character_profile'], photo='eval.png', background_image='eval.png')
    group = ChatGroup.objects.create(owner=user, name='固定评测群')
    group.characters.add(character)
    characters = {character.name: character}
    Friend.objects.create(me=profile, character=character, memory=case.get('private_fact', ''))
    SystemPrompt.objects.create(title='回复', order_number=1, prompt=system_prompt)
    if case.get('foreign_fact'):
        other = User.objects.create(username='其他评测用户')
        UserProfile.objects.create(user=other)
        foreign_group = ChatGroup.objects.create(owner=other, name='其他用户的私有群')
        GroupMessage.objects.create(group=foreign_group, role='user', sender_name=other.username,
            content=case['foreign_fact'], client_message_id=uuid4(), revision=1)
    previous_user = None
    revision = 0
    records = list(case.get('history', []))
    filler = [{'role': 'user', 'content': f'无关闲聊第{i + 1}轮：今天看看天气，暂时没有新计划。'} for i in range(case.get('filler_count', 0))]
    records += filler + case.get('recent_history', [])
    for item in records:
        revision += 1
        is_user = item['role'] == 'user'
        sender = user.username if is_user else item.get('sender', character.name)
        if not is_user and sender not in characters:
            characters[sender] = Character.objects.create(author=profile, name=sender,
                profile=f'你叫{sender}，只以自己的身份发言。', photo='eval.png', background_image='eval.png')
            group.characters.add(characters[sender])
        message = GroupMessage.objects.create(group=group, role=item['role'],
            sender_name=sender,
            character=None if is_user else characters[sender], content=item['content'], revision=revision,
            client_message_id=uuid4() if is_user else None, reply_to=None if is_user else previous_user)
        if is_user:
            previous_user = message
    question = GroupMessage.objects.create(group=group, role='user', sender_name=user.username,
        content=case['question'], client_message_id=uuid4(), revision=revision + 1)
    reply = GroupMessage.objects.create(group=group, role='ai', sender_name=character.name,
        character=character, reply_to=question, status='pending', revision=revision + 2)
    group.revision = revision + 2
    group.save(update_fields=['revision'])
    return create_inputs(reply)


def generate_answer(case, inputs):
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.messages import AIMessageChunk
    from web.views.friend.message.chat.graph import ChatGraph

    started = time.perf_counter()
    trace = []
    calls = {}

    class Capture(BaseCallbackHandler):
        def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
            metadata = kwargs.get('metadata', {})
            calls[str(run_id)] = {
                'started': time.perf_counter(), 'event': 'llm',
                'model': metadata.get('ls_model_name'), 'provider': metadata.get('ls_provider'),
                'temperature': metadata.get('ls_temperature'),
            }

        def on_llm_end(self, response, *, run_id, **kwargs):
            entry = calls.pop(str(run_id), {'started': time.perf_counter(), 'event': 'llm'})
            entry['duration_ms'] = round((time.perf_counter() - entry.pop('started')) * 1000, 2)
            usage = None
            for generation in response.generations:
                for item in generation:
                    reported = getattr(getattr(item, 'message', None), 'usage_metadata', None)
                    if reported:
                        usage = reported
            entry['usage'] = usage
            entry['status'] = 'completed'
            trace.append(entry)

        def on_llm_error(self, error, *, run_id, **kwargs):
            entry = calls.pop(str(run_id), {'started': time.perf_counter(), 'event': 'llm'})
            entry['duration_ms'] = round((time.perf_counter() - entry.pop('started')) * 1000, 2)
            entry.update(status='error', error_type=type(error).__name__)
            trace.append(entry)

        def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
            calls[str(run_id)] = {'started': time.perf_counter(), 'event': 'tool',
                'name': serialized.get('name'), 'input': input_str}

        def on_tool_end(self, output, *, run_id, **kwargs):
            entry = calls.pop(str(run_id), {'started': time.perf_counter(), 'event': 'tool'})
            entry['duration_ms'] = round((time.perf_counter() - entry.pop('started')) * 1000, 2)
            entry.update(status='completed', output=str(output)[:2000])
            trace.append(entry)

        def on_tool_error(self, error, *, run_id, **kwargs):
            entry = calls.pop(str(run_id), {'started': time.perf_counter(), 'event': 'tool'})
            entry['duration_ms'] = round((time.perf_counter() - entry.pop('started')) * 1000, 2)
            entry.update(status='error', error_type=type(error).__name__)
            trace.append(entry)

    answer = ''
    ttft = None
    error_type = None
    try:
        app = ChatGraph.create_app(timeout=45)
        for chunk, metadata in app.stream(inputs, stream_mode='messages',
                config={'recursion_limit': 12, 'callbacks': [Capture()]}):
            if not isinstance(chunk, AIMessageChunk) or metadata.get('langgraph_node') != 'agent':
                continue
            if isinstance(chunk.content, str) and chunk.content:
                if ttft is None:
                    ttft = round((time.perf_counter() - started) * 1000, 2)
                answer += chunk.content
        if not answer.strip():
            raise ValueError('Empty model answer')
    except Exception as error:
        # Record the type, never serialize SDK credentials/headers from exceptions.
        error_type = type(error).__name__
    usage = {}
    for field in ['input_tokens', 'output_tokens', 'total_tokens']:
        values = [entry['usage'][field] for entry in trace if entry.get('usage') and field in entry['usage']]
        usage[field] = sum(values) if values else None
    return {
        'status': 'error' if error_type else 'completed', 'error_type': error_type,
        'answer': answer, 'duration_ms': round((time.perf_counter() - started) * 1000, 2),
        'ttft_ms': ttft, 'usage': usage, 'trace': trace,
        'grading': grade_answer(case, answer) if not error_type else {'status': 'not_run'},
    }


def run_case(case, runner, system_prompt, live):
    if case['kind'] == 'engineering':
        result = unittest.TestResult()
        runner.build_suite([case['test']]).run(result)
        status = 'error' if result.errors else 'failed' if result.failures else 'skipped' if result.skipped else 'passed'
        if result.testsRun != 1:
            status = 'error'
        return {'engineering': {'status': status, 'tests_run': result.testsRun,
            'details': [text for _, text in result.errors + result.failures + result.skipped]}}
    from django.db import transaction
    with transaction.atomic():
        inputs = prepare_conversation(case, system_prompt)
        output = {
            'context': check_context(case, inputs),
            'inputs': [{'role': m.type, 'content': m.content} for m in inputs['messages']],
            'prompt_sha256': hashlib.sha256('\n'.join(m.content for m in inputs['messages']).encode()).hexdigest(),
            'quality': generate_answer(case, inputs) if live else {'status': 'not_run'},
        }
        transaction.set_rollback(True)
        return output


def main():
    parser = argparse.ArgumentParser(description='AI group baseline: offline by default; --live calls the configured LLM.')
    parser.add_argument('--dataset', type=Path, default=ROOT / 'test/datasets/baseline.json')
    parser.add_argument('--live', action='store_true', help='Explicitly enable external model/tool calls; never calls speech APIs')
    parser.add_argument('--case', action='append', default=[], help='Select case id; may be repeated')
    parser.add_argument('--category', action='append', default=[], help='Select category; may be repeated')
    parser.add_argument('--repeat', type=int, default=1, help='Trials per conversation; engineering checks run once')
    parser.add_argument('--list', action='store_true', help='List selected cases without running Django or API calls')
    parser.add_argument('--strict', action='store_true', help='Also fail the command on context/answer-rule gaps')
    args = parser.parse_args()
    if not 1 <= args.repeat <= 10:
        parser.error('--repeat must be 1..10')
    dataset = load_dataset(args.dataset.resolve())
    known_ids = {c['id'] for c in dataset['cases']}
    known_categories = {c['category'] for c in dataset['cases']}
    if set(args.case) - known_ids or set(args.category) - known_categories:
        parser.error('Unknown case/category; use --list')
    cases = [c for c in dataset['cases'] if (not args.case or c['id'] in args.case) and (not args.category or c['category'] in args.category)]
    if not cases:
        parser.error('No cases selected')
    if args.list:
        for case in cases:
            print(f'{case["id"]:30} {case["kind"]:12} {case["category"]}')
        return 0
    timestamp = datetime.now(ZoneInfo('Asia/Shanghai'))
    run_id = timestamp.strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8]
    report = {
        'run_id': run_id, 'started_at': timestamp.isoformat(), 'mode': 'live' if args.live else 'offline',
        'dataset_version': dataset['version'], 'dataset_sha256': dataset['sha256'], 'repeat': args.repeat,
        'scope': 'Private AI group; synthetic fixtures; production create_inputs + ChatGraph; no ASR/TTS',
        'grading': 'Substring checks are diagnostic; human review required. Offline is not model quality.',
        'source_sha256': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in [
            'backend/web/views/group.py', 'backend/web/views/group_worker.py',
            'backend/web/views/friend/message/chat/graph.py', 'requirements.txt',
            'test/run.py', 'test/evaluation.py']},
        'cases': [],
    }
    for key, command in [('git_commit', ['git', 'rev-parse', 'HEAD']), ('git_status', ['git', 'status', '--porcelain', '--untracked-files=normal'])]:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=5)
        report[key] = result.stdout.strip() if result.returncode == 0 else None
    with temporary_workspace() as directory, ExitStack() as stack:
        configure_django(directory)
        from django.test.runner import DiscoverRunner
        from unittest.mock import patch
        runner = DiscoverRunner(verbosity=0, interactive=False)
        runner.setup_test_environment()
        database_config = runner.setup_databases()
        if not args.live:
            # Block API entry points, leaving Windows asyncio's local socketpair intact.
            for target in ['httpx.Client.send', 'httpx.AsyncClient.send', 'requests.sessions.Session.send',
                           'websockets.connect', 'web.views.friend.message.chat.graph.ChatGraph.create_app']:
                stack.enter_context(patch(target, side_effect=RuntimeError('Network disabled in offline evaluation')))
        try:
            for case in cases:
                for trial in range(1, (args.repeat if case['kind'] == 'conversation' else 1) + 1):
                    row = {key: case[key] for key in ['id', 'category', 'kind', 'rubric']}
                    row.update(trial=trial, trace_id=f'{run_id}:{case["id"]}:{trial}')
                    if report.get('aborted') and case['kind'] == 'conversation':
                        row.update(context={'status': 'not_run'}, quality={'status': 'not_run'}, reason='previous_model_error')
                    else:
                        try:
                            row.update(run_case(case, runner, dataset['reply_system_prompt'], args.live))
                        except Exception as error:
                            row['error_type'] = type(error).__name__
                            if case['kind'] == 'engineering':
                                row['engineering'] = {'status': 'error'}
                            else:
                                row.update(context={'status': 'error'}, quality={'status': 'not_run'})
                    report['cases'].append(row)
                    status = row.get('engineering', row.get('context', {}))['status']
                    print(f'{case["id"]} #{trial}: {status}' + (f' / model={row["quality"]["status"]}' if 'quality' in row else ''))
                    if row.get('quality', {}).get('status') == 'error':
                        print('Stopping live calls after provider/graph error; remaining conversation cases will not run.')
                        report['aborted'] = True
        finally:
            runner.teardown_databases(database_config)
            runner.teardown_test_environment()
    report['selected_cases'] = len(cases)
    report['summary'] = summarize(report['cases'])
    output = ROOT / 'test/results' / run_id
    write_report(output, report)
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    print(f'Report: {output / "report.json"}')
    print(f'CSV: {output / "cases.csv"}')
    summary = report['summary']
    failed = any(status != 'passed' for status in summary['engineering']) or summary['model'].get('error', 0) or summary['context'].get('error', 0)
    if args.strict:
        failed = failed or summary['context'].get('failed', 0) or summary['answer_rules'].get('failed', 0)
    return int(bool(failed))


if __name__ == '__main__':
    raise SystemExit(main())

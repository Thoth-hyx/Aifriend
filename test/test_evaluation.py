import csv
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from evaluation import check_context, grade_answer, load_dataset, percentile, summarize, write_report
from run import ROOT, configure_django, generate_answer, main, temporary_workspace


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.case = {'answer_any': [['AI应用开发', 'AI工程师']], 'forbidden_answer': ['Java后端']}

    def test_grade_handles_alternatives_empty_answer_and_forbidden_text(self):
        self.assertEqual(grade_answer(self.case, 'AI 应用开发')['status'], 'passed')
        self.assertEqual(grade_answer(self.case, 'AI工程师')['status'], 'passed')
        self.assertEqual(grade_answer(self.case, '')['status'], 'failed')
        self.assertEqual(grade_answer(self.case, 'AI应用开发与Java后端')['status'], 'failed')
        self.assertTrue(grade_answer(self.case, 'AI应用开发')['human_review_required'])

    def test_context_checks_loss_and_leak_separately(self):
        case = {'required_context': ['香菜'], 'forbidden_context': ['SECRET']}
        checked = check_context(case, {'messages': [SimpleNamespace(content='这里出现了SECRET')]})
        self.assertEqual(checked['missing'], ['香菜'])
        self.assertEqual(checked['leaked'], ['SECRET'])
        self.assertEqual(checked['status'], 'failed')

    def test_dataset_validation_rejects_duplicates_and_bad_history(self):
        data = json.loads((ROOT / 'test/datasets/baseline.json').read_text(encoding='utf-8'))
        self.assertEqual(len(load_dataset(ROOT / 'test/datasets/baseline.json')['cases']), 32)
        with temporary_workspace() as directory:
            path = Path(directory) / 'bad.json'
            data['cases'].append(data['cases'][0])
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                load_dataset(path)
            data['cases'].pop()
            data['cases'][-1]['recent_history'] = [{'role': 'invalid', 'content': 'bad'}]
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'history'):
                load_dataset(path)

    def test_offline_and_error_outputs_do_not_become_quality_successes(self):
        row = {'id': 'sample', 'category': 'memory', 'kind': 'conversation', 'context': {'status': 'failed'}, 'quality': {'status': 'not_run'}}
        summary = summarize([row])
        self.assertEqual(summary['context'], {'failed': 1})
        self.assertEqual(summary['model'], {'not_run': 1})
        self.assertIsNone(summary['answer_rule_pass_rate_completed_only'])
        self.assertIsNone(summary['answer_rule_pass_rate_attempted'])
        self.assertIsNone(summary['categories']['memory']['answer_rule_failed'])
        self.assertIsNone(summary['total_tokens'])
        self.assertIsNone(summary['p95_duration_ms'])
        row['quality'] = {'status': 'error', 'usage': {'total_tokens': 17}}
        summary = summarize([row])
        self.assertEqual(summary['model'], {'error': 1})
        self.assertEqual(summary['total_tokens'], 17)
        self.assertIsNone(summary['answer_rule_pass_rate_completed_only'])
        self.assertEqual(percentile([10, 20, 30], .95), 30)

    def test_report_preserves_json_and_neutralizes_csv_formulas(self):
        row = {'id': 'sample', 'trial': 1, 'category': 'persona', 'kind': 'conversation', 'rubric': '人工复核',
            'context': {'status': 'passed'}, 'quality': {'status': 'completed', 'answer': '=HYPERLINK("example")'}}
        with temporary_workspace() as directory:
            output = Path(directory) / 'run'
            write_report(output, {'cases': [row]})
            self.assertEqual(json.loads((output / 'report.json').read_text(encoding='utf-8'))['cases'][0]['quality']['answer'], row['quality']['answer'])
            with (output / 'cases.csv').open(encoding='utf-8-sig', newline='') as file:
                self.assertEqual(next(csv.DictReader(file))['answer'], "'" + row['quality']['answer'])


class LiveAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = temporary_workspace()
        configure_django(cls.directory.name)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_graph_trace_usage_and_non_agent_filter_with_mocked_model(self):
        from langchain_core.messages import AIMessageChunk, ToolMessageChunk
        case = {'answer_any': [['林老师']], 'forbidden_answer': []}

        def stream(inputs, *, stream_mode, config):
            callback = config['callbacks'][0]
            for input_tokens, output_tokens in [(10, 2), (4, 2)]:
                call_id = uuid4()
                callback.on_chat_model_start({}, [], run_id=call_id, metadata={'ls_model_name': 'mock-model'})
                callback.on_llm_end(SimpleNamespace(generations=[[SimpleNamespace(message=SimpleNamespace(
                    usage_metadata={'input_tokens': input_tokens, 'output_tokens': output_tokens, 'total_tokens': input_tokens + output_tokens}
                ))]]), run_id=call_id)
            tool_id = uuid4()
            callback.on_tool_start({'name': 'get_time'}, '{}', run_id=tool_id)
            callback.on_tool_end('mock time', run_id=tool_id)
            yield ToolMessageChunk(content='不能作为回答', tool_call_id='id'), {'langgraph_node': 'tools'}
            yield AIMessageChunk(content='不能作为回答'), {'langgraph_node': 'tools'}
            yield AIMessageChunk(content='林老师'), {'langgraph_node': 'agent'}

        app = Mock()
        app.stream.side_effect = stream
        with patch('web.views.friend.message.chat.graph.ChatGraph.create_app', return_value=app) as factory:
            result = generate_answer(case, {'messages': []})
        factory.assert_called_once_with(timeout=45)
        self.assertEqual(result['answer'], '林老师')
        self.assertEqual(result['grading']['status'], 'passed')
        self.assertEqual(result['usage'], {'input_tokens': 14, 'output_tokens': 4, 'total_tokens': 18})
        self.assertEqual(len(result['trace']), 3)
        self.assertEqual(result['trace'][0]['model'], 'mock-model')
        self.assertIsNotNone(result['ttft_ms'])

    def test_provider_failure_and_empty_response_are_not_graded(self):
        case = {'answer_any': [['林老师']], 'forbidden_answer': []}
        with patch('web.views.friend.message.chat.graph.ChatGraph.create_app', side_effect=RuntimeError('DO_NOT_LOG_SECRET')):
            result = generate_answer(case, {'messages': []})
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error_type'], 'RuntimeError')
        self.assertNotIn('DO_NOT_LOG_SECRET', json.dumps(result))
        self.assertEqual(result['grading']['status'], 'not_run')
        app = Mock()
        app.stream.return_value = iter([])
        with patch('web.views.friend.message.chat.graph.ChatGraph.create_app', return_value=app):
            self.assertEqual(generate_answer(case, {'messages': []})['status'], 'error')

    def test_live_cli_stops_calls_after_error_and_reports_unrun_cases(self):
        failure = {'status': 'error', 'error_type': 'MockProviderError', 'usage': {}, 'grading': {'status': 'not_run'}}
        with patch('sys.argv', ['run.py', '--live', '--category', 'persona']), patch(
            'run.generate_answer', return_value=failure,
        ) as generate, patch('run.write_report') as write, redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 1)
        generate.assert_called_once()
        report = write.call_args.args[1]
        self.assertTrue(report['aborted'])
        self.assertEqual(report['selected_cases'], 2)
        self.assertEqual(len(report['cases']), 2)
        self.assertEqual(report['summary']['model'], {'error': 1, 'not_run': 1})
        self.assertEqual(report['cases'][1]['reason'], 'previous_model_error')


if __name__ == '__main__':
    unittest.main()

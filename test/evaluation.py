"""Dataset validation, deterministic checks and report output; no model calls."""
import csv
import hashlib
import json
import math
import unicodedata
from collections import Counter
from pathlib import Path


def normalize(text):
    return ''.join(unicodedata.normalize('NFKC', text).casefold().split())


def load_dataset(path):
    raw = Path(path).read_bytes()
    data = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data, dict) or not isinstance(data.get('version'), str) or not isinstance(data.get('reply_system_prompt'), str):
        raise ValueError('Dataset needs version and reply_system_prompt strings')
    cases = data.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('Dataset needs a nonempty cases list')
    ids = set()
    for case in cases:
        for field in ['id', 'category', 'kind', 'rubric']:
            if not isinstance(case.get(field), str) or not case[field].strip():
                raise ValueError(f'Invalid {field}: {case}')
        if case['id'] in ids:
            raise ValueError(f'Duplicate case id: {case["id"]}')
        ids.add(case['id'])
        if case['kind'] == 'engineering':
            label = case.get('test', '')
            if not label.startswith(('web.test_group_im.GroupIMTests.test_', 'web.test_startup.StartupTests.test_')):
                raise ValueError(f'Unsupported engineering test: {label}')
            continue
        if case['kind'] != 'conversation':
            raise ValueError(f'Unknown kind: {case["kind"]}')
        for field in ['question', 'character_name', 'character_profile']:
            if not isinstance(case.get(field), str) or not case[field].strip():
                raise ValueError(f'{case["id"]}: invalid {field}')
        history = case.get('history', [])
        recent = case.get('recent_history', [])
        if not isinstance(history, list) or not isinstance(recent, list):
            raise ValueError(f'{case["id"]}: history must be a list')
        for item in history + recent:
            if not isinstance(item, dict) or item.get('role') not in ['user', 'ai'] or not isinstance(item.get('content'), str):
                raise ValueError(f'{case["id"]}: invalid history item')
            if 'sender' in item and not isinstance(item['sender'], str):
                raise ValueError(f'{case["id"]}: invalid sender')
        filler = case.get('filler_count', 0)
        if type(filler) is not int or not 0 <= filler <= 200:
            raise ValueError(f'{case["id"]}: filler_count must be 0..200')
        for field in ['required_context', 'forbidden_context', 'forbidden_answer']:
            if not isinstance(case.get(field, []), list) or any(not isinstance(s, str) or not s.strip() for s in case.get(field, [])):
                raise ValueError(f'{case["id"]}: invalid {field}')
        groups = case.get('answer_any', [])
        if not groups or any(not isinstance(g, list) or not g or any(not isinstance(s, str) or not s.strip() for s in g) for g in groups):
            raise ValueError(f'{case["id"]}: answer_any needs nonempty alternative groups')
        for field in ['foreign_fact', 'private_fact']:
            if field in case and not isinstance(case[field], str):
                raise ValueError(f'{case["id"]}: invalid {field}')
    data['sha256'] = hashlib.sha256(raw).hexdigest()
    return data


def check_context(case, inputs):
    text = normalize('\n'.join(message.content for message in inputs['messages']))
    missing = [s for s in case.get('required_context', []) if normalize(s) not in text]
    leaked = [s for s in case.get('forbidden_context', []) if normalize(s) in text]
    return {'status': 'failed' if missing or leaked else 'passed', 'missing': missing, 'leaked': leaked}


def grade_answer(case, answer):
    # ponytail: substring rules are a regression signal, not semantic correctness; keep human review.
    text = normalize(answer)
    missing = [group for group in case['answer_any'] if not any(normalize(s) in text for s in group)]
    forbidden = [s for s in case.get('forbidden_answer', []) if normalize(s) in text]
    return {
        'status': 'passed' if text and not missing and not forbidden else 'failed',
        'missing_alternatives': missing, 'forbidden_matches': forbidden,
        'human_review_required': True,
    }


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 2)


def summarize(rows):
    engineering = Counter(r['engineering']['status'] for r in rows if r['kind'] == 'engineering')
    conversations = [r for r in rows if r['kind'] == 'conversation']
    context = Counter(r['context']['status'] for r in conversations)
    quality = Counter(r['quality']['status'] for r in conversations)
    grades = Counter(r['quality']['grading']['status'] for r in conversations if r['quality']['status'] == 'completed')
    completed = [r['quality'] for r in conversations if r['quality']['status'] == 'completed']
    summary = {
        'engineering': dict(engineering), 'context': dict(context), 'model': dict(quality),
        'answer_rules': dict(grades),
        'model_attempted': quality['completed'] + quality['error'],
        'answer_rule_pass_rate_completed_only': grades['passed'] / sum(grades.values()) if grades else None,
        'answer_rule_pass_rate_attempted': grades['passed'] / (quality['completed'] + quality['error']) if quality['completed'] + quality['error'] else None,
        'categories': {},
    }
    for category in sorted({r['category'] for r in rows}):
        selected = [r for r in rows if r['category'] == category]
        summary['categories'][category] = {
            'cases': len(selected),
            'context_failed': sum(r.get('context', {}).get('status') == 'failed' for r in selected) if any(r.get('context', {}).get('status') in ['passed', 'failed'] for r in selected) else None,
            'answer_rule_failed': sum(r.get('quality', {}).get('grading', {}).get('status') == 'failed' for r in selected) if any(r.get('quality', {}).get('grading', {}).get('status') in ['passed', 'failed'] for r in selected) else None,
        }
    for field in ['duration_ms', 'ttft_ms']:
        values = [r[field] for r in completed if r.get(field) is not None]
        for name, fraction in [('p50', .5), ('p95', .95)]:
            summary[f'{name}_{field}'] = percentile(values, fraction)
    for field in ['input_tokens', 'output_tokens', 'total_tokens']:
        values = [r['usage'][field] for r in conversations_quality(rows) if r.get('usage', {}).get(field) is not None]
        summary[field] = sum(values) if values else None
    summary['usage_reported_cases'] = sum(r.get('usage', {}).get('total_tokens') is not None for r in conversations_quality(rows))
    return summary


def conversations_quality(rows):
    return [r['quality'] for r in rows if r['kind'] == 'conversation' and r['quality']['status'] != 'not_run']


def write_report(directory, report):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    fields = ['id', 'trial', 'category', 'kind', 'engineering', 'context', 'model', 'answer_rules',
              'duration_ms', 'ttft_ms', 'input_tokens', 'output_tokens', 'error_type', 'answer', 'rubric']
    with (directory / 'cases.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in report['cases']:
            quality = row.get('quality', {})
            cells = {
                'id': row['id'], 'trial': row['trial'], 'category': row['category'], 'kind': row['kind'],
                'engineering': row.get('engineering', {}).get('status', ''),
                'context': row.get('context', {}).get('status', ''), 'model': quality.get('status', ''),
                'answer_rules': quality.get('grading', {}).get('status', ''),
                'duration_ms': quality.get('duration_ms'), 'ttft_ms': quality.get('ttft_ms'),
                'input_tokens': quality.get('usage', {}).get('input_tokens'),
                'output_tokens': quality.get('usage', {}).get('output_tokens'),
                'error_type': quality.get('error_type', ''), 'answer': quality.get('answer', ''), 'rubric': row['rubric'],
            }
            # Spreadsheet apps must treat model answers as text, never formulas.
            writer.writerow({key: "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value for key, value in cells.items()})

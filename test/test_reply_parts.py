import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from web.views.utils.reply_parts import ReplyStream, split_reply
from run import configure_django, temporary_workspace


class ReplyPartsTests(unittest.TestCase):
    def test_split_is_bounded_and_does_not_drop_extra_text(self):
        for text, expected in [
            ('', []), ('  你好  ', ['你好']), ('甲。乙！丙？丁。', ['甲。', '乙！', '丙？丁。']),
            ('甲\n\n乙\n\n丙\n\n丁', ['甲', '乙', '丙\n\n丁']),
            ('Hello. How are you? Fine!', ['Hello.', 'How are you?', 'Fine!']),
            ('列表：\n- 甲\n- 乙', ['列表：\n- 甲\n- 乙']),
            ('说明\n\n```python\nx = 1\n\nprint(x)\n```', ['说明', '```python\nx = 1\n\nprint(x)\n```']),
            ('1. 第一项\n2. 第二项', ['1. 第一项\n2. 第二项']),
            ('“你好。” 下一条。再下一条。更多内容。', ['“你好。”', '下一条。', '再下一条。更多内容。']),
        ]:
            with self.subTest(text=text):
                self.assertEqual(split_reply(text), expected)
                self.assertLessEqual(len(split_reply(text)), 3)

    def test_stream_is_append_only_and_independent_of_chunk_boundaries(self):
        for text in [
            '甲。乙！丙？丁。', '“你好？！” 下一句。\n\n第三句。尾巴。',
            'Hello. How are you? Fine! More.', '价格为 3.14 元。下一条。',
            '前言。\n\n```python\nx = 1.0\n\nprint("甲。乙。")\n```\n\n后记。',
            '~~~text\n甲。乙。\n~~~\n\n后记。', '列表：\n1. 第一项\n2. 第二项', '   \n\n',
        ]:
            expected = split_reply(text)
            for width in range(1, len(text) + 1):
                stream = ReplyStream()
                displayed = {}
                for start in range(0, len(text), width):
                    old = stream.parts
                    for event in stream.feed(text[start:start + width]):
                        index = event['part_index']
                        self.assertLess(index, 3)
                        displayed[index] = displayed.get(index, '') + event['content']
                    self.assertEqual(list(displayed.values()), stream.parts)
                    for index, part in enumerate(old):
                        self.assertTrue(stream.parts[index].startswith(part), (text, width))
                self.assertEqual(stream.parts, expected, (text, width))

    def test_second_bubble_starts_before_generation_finishes(self):
        stream = ReplyStream()
        self.assertEqual(stream.feed('你好。'), [{'part_index': 0, 'content': '你好。'}])
        self.assertEqual(stream.feed('第二'), [{'part_index': 1, 'content': '第二'}])
        self.assertEqual(stream.feed('条。第三条。第四条。'), [
            {'part_index': 1, 'content': '条。'}, {'part_index': 2, 'content': '第三条。第四条。'},
        ])
        self.assertEqual(stream.parts, ['你好。', '第二条。', '第三条。第四条。'])

    def test_real_group_sync_and_private_sse_history_use_same_parts(self):
        with temporary_workspace() as directory:
            configure_django(directory)
            from django.contrib.auth.models import User
            from django.test import TestCase
            from django.test.runner import DiscoverRunner
            from langchain_core.messages import AIMessageChunk
            from rest_framework.test import APIClient
            from web.models.character import Character, Voice
            from web.models.friend import Friend, Message
            from web.models.group import ChatGroup, GroupMessage
            from web.models.user import UserProfile
            from web.views.friend.message.chat.chat import MessageChatView
            from web.views.group_worker import claim_reply, process_next, save_reply

            checks = self

            class FlowChecks(TestCase):
                def runTest(self):
                    user = User.objects.create_user(username='reply-eval')
                    profile = UserProfile.objects.create(user=user)
                    voice = Voice.objects.create(name='评测音色', voice_id='fake-voice')
                    character = Character.objects.create(author=profile, name='角色', profile='测试',
                        photo='test.png', background_image='test.png', voice=voice)
                    friend = Friend.objects.create(me=profile, character=character)
                    group = ChatGroup.objects.create(owner=user, name='评测群')
                    group.characters.add(character)
                    client = APIClient()
                    client.force_authenticate(user)
                    url = f'/api/groups/{group.pk}/messages/'
                    body = {'content': '你好', 'client_message_id': str(uuid4())}
                    sent = client.post(url, body, format='json')
                    cursor = client.get(url).data['cursor']
                    answer = '第一条。第二条。第三条。第四条。'
                    parts = split_reply(answer)
                    app = Mock()
                    app.stream.return_value = iter([(AIMessageChunk(content=answer), {'langgraph_node': 'agent'})])
                    with patch('web.views.group_worker.ChatGraph.create_app', return_value=app):
                        checks.assertTrue(process_next())
                    delta = client.get(url, {'after_revision': cursor}).data['messages']
                    checks.assertEqual(delta[0]['reply_parts'], parts)
                    checks.assertEqual(delta[0]['id'], sent.data['messages'][1]['id'])
                    checks.assertEqual(delta[0]['content'], answer)
                    checks.assertEqual(GroupMessage.objects.count(), 2)
                    duplicate = client.post(url, body, format='json').data['messages'][1]
                    checks.assertEqual(duplicate['reply_parts'], parts)
                    checks.assertEqual(client.get(url, {'after_revision': 0}).data['messages'][1]['reply_parts'], parts)
                    checks.assertEqual(client.get(url, {'after_revision': client.get(url).data['cursor']}).data['messages'], [])
                    client.post(url, {**body, 'client_message_id': str(uuid4())}, format='json')
                    old = claim_reply()
                    save_reply(old, 'failed', '部分回复', '失败')
                    checks.assertEqual(client.get(url).data['messages'][-1]['reply_parts'], [])
                    client.post(f'{url}{old.pk}/retry/')
                    new = claim_reply()
                    checks.assertFalse(save_reply(old, 'completed', answer))
                    checks.assertTrue(save_reply(new, 'completed', answer))
                    checks.assertEqual(GroupMessage.objects.count(), 4)

                    long_answer = '第一段' + '甲' * 600 + '\n\n第二段\n\n第三段\n\n第四段'
                    def fake_work(app, inputs, queue, voice_id):
                        queue.put({'content': long_answer})
                        queue.put({'usage': {'total_tokens': 12}})
                        queue.put(None)
                    with patch.object(MessageChatView, 'work', side_effect=fake_work), patch(
                        'web.views.friend.message.chat.chat.update_memory',
                    ):
                        response = MessageChatView().event_stream(Mock(), {'messages': []}, friend, '用户输入')
                        first = next(response)
                        checks.assertFalse(Message.objects.filter(friend=friend).exists())
                        events = [first, *response]
                    events = [json.loads(event[5:]) for event in events if '[DONE]' not in event]
                    streamed = {}
                    for event in events:
                        checks.assertNotIn('reply_parts', event)
                        if event.get('content'):
                            index = event['part_index']
                            streamed[index] = streamed.get(index, '') + event['content']
                    checks.assertEqual(list(streamed.values()), split_reply(long_answer))
                    checks.assertEqual(Message.objects.get(friend=friend).output, long_answer)
                    history = client.get('/api/friend/message/get_history/', {'friend_id': friend.pk, 'last_message_id': 0}).data
                    checks.assertEqual(history['messages'][0]['reply_parts'], list(streamed.values()))
                    checks.assertEqual(len(history['messages']), 1)

            runner = DiscoverRunner(verbosity=0, interactive=False)
            runner.setup_test_environment()
            database = runner.setup_databases()
            try:
                result = runner.run_suite(unittest.TestSuite([FlowChecks()]))
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
            finally:
                runner.teardown_databases(database)
                runner.teardown_test_environment()

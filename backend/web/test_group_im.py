from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils.timezone import now
from langchain_core.messages import AIMessageChunk, ToolMessageChunk
from rest_framework.test import APIClient

from web.models.character import Character
from web.models.friend import Friend
from web.models.group import ChatGroup, GroupMessage
from web.models.user import UserProfile
from web.views.group_worker import claim_reply, process_next, recover_stale, save_reply


class GroupIMTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='owner')
        cls.other = User.objects.create_user(username='other')
        profile = UserProfile.objects.create(user=cls.user)
        UserProfile.objects.create(user=cls.other)
        cls.characters = [Character.objects.create(
            author=profile, name=name, profile=f'{name}的人设',
            photo='test.png', background_image='test.png',
        ) for name in ['角色甲', '角色乙', '陌生角色']]
        for character in cls.characters[:2]:
            Friend.objects.create(me=profile, character=character)
        cls.group = ChatGroup.objects.create(owner=cls.user, name='讨论群')
        cls.group.characters.add(*cls.characters[:2])

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.messages_url = f'/api/groups/{self.group.pk}/messages/'

    def send(self, content='你好', target=None, client_id=None):
        return self.client.post(self.messages_url, {
            'content': content, 'character_id': target,
            'client_message_id': str(client_id or uuid4()),
        }, format='json')

    def test_ownership_and_friend_invitation(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/groups/').data['groups'], [])
        self.assertEqual(self.client.get(self.messages_url).status_code, 404)
        self.assertEqual(self.send().status_code, 404)
        self.assertEqual(self.client.post(f'/api/groups/{self.group.pk}/characters/', {'character_id': self.characters[0].pk}).status_code, 404)
        self.client.force_authenticate(self.user)
        url = f'/api/groups/{self.group.pk}/characters/'
        self.assertEqual(self.client.post(url, {'character_id': self.characters[2].pk}).status_code, 400)
        for _ in range(2):
            self.assertEqual(self.client.post(url, {'character_id': self.characters[0].pk}).status_code, 200)
        self.assertEqual(self.group.characters.count(), 2)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/groups/').status_code, 401)

    def test_random_single_reply_and_idempotent_send(self):
        client_id = uuid4()
        with patch('web.views.group.random.choice', return_value=self.characters[1]) as choose:
            first = self.send(client_id=client_id)
            second = self.send(client_id=client_id)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['messages'], second.data['messages'])
        self.assertEqual(GroupMessage.objects.count(), 2)
        self.assertEqual(first.data['messages'][1]['character_id'], self.characters[1].pk)
        self.assertEqual(first.data['messages'][1]['status'], 'pending')
        choose.assert_called_once()
        self.assertEqual(self.send(content='不同消息', client_id=client_id).status_code, 409)

    def test_remove_member_keeps_friend_history_and_fences_unfinished_replies(self):
        character = self.characters[0]
        other_group = ChatGroup.objects.create(owner=self.user, name='另一个群')
        other_group.characters.add(character)
        self.send(target=character.pk)
        generating = claim_reply()
        save_reply(generating, 'generating', '已经生成的内容')
        self.send(target=character.pk, content='排队的问题')
        self.send(target=self.characters[1].pk, content='其他成员的问题')
        initial = self.client.get(self.messages_url).data
        url = f'/api/groups/{self.group.pk}/characters/'
        result = self.client.delete(url, {'character_id': character.pk}, format='json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual([c['id'] for c in result.data['group']['characters']], [self.characters[1].pk])
        self.assertTrue(Friend.objects.filter(me__user=self.user, character=character).exists())
        self.assertTrue(Character.objects.filter(pk=character.pk).exists())
        self.assertTrue(other_group.characters.filter(pk=character.pk).exists())
        self.assertEqual(GroupMessage.objects.count(), 6)
        cancelled = GroupMessage.objects.filter(role='ai', character=character)
        self.assertEqual(list(cancelled.values_list('status', flat=True)), ['failed', 'failed'])
        self.assertEqual(cancelled.get(pk=generating.pk).content, '已经生成的内容')
        self.assertFalse(save_reply(generating, 'completed', '迟到的结果'))
        delta = self.client.get(self.messages_url, {'after_revision': initial['cursor']}).data
        self.assertEqual(len(delta['messages']), 2)
        self.assertTrue(all(message['sender_photo'].endswith('/test.png') for message in delta['messages']))
        self.assertTrue(all(message['error'] == '角色已移出群聊，回复已停止' for message in delta['messages']))
        self.assertEqual(self.send(target=character.pk).status_code, 400)
        retry_url = f'{self.messages_url}{generating.pk}/retry/'
        self.assertEqual(self.client.post(retry_url).status_code, 400)
        self.assertEqual(claim_reply().character_id, self.characters[1].pk)
        self.assertEqual(self.client.post(url, {'character_id': character.pk}).status_code, 200)
        self.assertEqual(self.client.post(retry_url).status_code, 200)

    def test_remove_member_permissions_validation_and_empty_group(self):
        url = f'/api/groups/{self.group.pk}/characters/'
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.delete(url, {'character_id': self.characters[0].pk}, format='json').status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.delete(url, {'character_id': self.characters[0].pk}, format='json').status_code, 401)
        self.client.force_authenticate(self.user)
        for invalid in [None, True, -1, 'bad']:
            self.assertEqual(self.client.delete(url, {'character_id': invalid}, format='json').status_code, 400)
        self.assertEqual(self.group.characters.count(), 2)
        self.send(target=self.characters[0].pk)
        for character in self.characters[:2]:
            for _ in range(2):
                self.assertEqual(self.client.delete(url, {'character_id': character.pk}, format='json').status_code, 200)
        self.assertIsNone(claim_reply())
        self.assertEqual(self.send().status_code, 400)
        self.assertEqual(Friend.objects.filter(me__user=self.user).count(), 2)
        self.assertEqual(GroupMessage.objects.count(), 2)

    def test_explicit_target_and_validation(self):
        with patch('web.views.group.random.choice') as choose:
            reply = self.send(target=self.characters[0].pk).data['messages'][1]
        choose.assert_not_called()
        self.assertEqual(reply['character_id'], self.characters[0].pk)
        self.assertEqual(self.send(target=self.characters[2].pk).status_code, 400)
        self.assertEqual(self.send(content=' ').status_code, 400)
        self.assertEqual(self.send(content='长' * 2001).status_code, 400)
        self.assertEqual(self.client.post(self.messages_url, {'content': '你好', 'client_message_id': 'bad'}, format='json').status_code, 400)
        self.assertEqual(self.client.get(self.messages_url, {'after_revision': -1}).status_code, 400)
        empty = ChatGroup.objects.create(owner=self.user, name='空群')
        self.assertEqual(self.client.post(f'/api/groups/{empty.pk}/messages/', {'content': '你好', 'client_message_id': str(uuid4())}, format='json').status_code, 400)

    def test_disconnect_sync_includes_updates_to_old_messages(self):
        self.send()
        initial = self.client.get(self.messages_url).data
        reply = claim_reply()
        save_reply(reply, 'generating', '正在写')
        delta = self.client.get(self.messages_url, {'after_revision': initial['cursor']}).data
        self.assertEqual(len(delta['messages']), 1)
        self.assertEqual(delta['messages'][0]['id'], reply.id)
        self.assertEqual(delta['messages'][0]['content'], '正在写')
        save_reply(reply, 'completed', '完整回答' * 300)
        recovered = self.client.get(self.messages_url, {'after_revision': delta['cursor']}).data
        self.assertEqual(recovered['messages'][0]['status'], 'completed')
        self.assertGreater(len(recovered['messages'][0]['content']), 500)
        self.assertEqual(self.client.get(self.messages_url, {'after_revision': recovered['cursor']}).data['messages'], [])

    def test_sync_pagination_and_independent_conversations(self):
        GroupMessage.objects.bulk_create([GroupMessage(
            group=self.group, role='user', sender_name='owner', content=str(i),
            client_message_id=uuid4(), revision=i,
        ) for i in range(1, 106)])
        ChatGroup.objects.filter(pk=self.group.pk).update(revision=105)
        first = self.client.get(self.messages_url).data
        second = self.client.get(self.messages_url, {'after_revision': first['cursor']}).data
        self.assertEqual(len(first['messages']), 100)
        self.assertTrue(first['has_more'])
        self.assertEqual(len(second['messages']), 5)
        self.assertFalse(second['has_more'])
        other_group = ChatGroup.objects.create(owner=self.user, name='另一会话')
        other_group.characters.add(self.characters[0])
        result = self.client.get(f'/api/groups/{other_group.pk}/messages/').data
        self.assertEqual(result['messages'], [])
        self.assertEqual(result['cursor'], 0)

    def test_worker_completion_and_frozen_context(self):
        self.send(content='第一个问题')
        self.send(content='后来的问题')
        app = Mock()
        app.stream.return_value = iter([
            (ToolMessageChunk(content='不能显示的工具结果', tool_call_id='tool'), {'langgraph_node': 'tools'}),
            (AIMessageChunk(content='你好'), {'langgraph_node': 'agent'}),
            (AIMessageChunk(content='，我是角色'), {'langgraph_node': 'agent'}),
        ])
        with patch('web.views.group_worker.ChatGraph.create_app', return_value=app):
            self.assertTrue(process_next())
        reply = GroupMessage.objects.filter(role='ai').order_by('id').first()
        self.assertEqual(reply.status, 'completed')
        self.assertEqual(reply.content, '你好，我是角色')
        inputs = app.stream.call_args.args[0]
        self.assertIn('第一个问题', inputs['messages'][-1].content)
        self.assertNotIn('后来的问题', inputs['messages'][-1].content)
        self.assertEqual(GroupMessage.objects.filter(status='pending').count(), 1)

    def test_serial_claim_failure_retry_and_old_attempt_is_fenced(self):
        self.send()
        self.send(content='第二条')
        reply = claim_reply()
        self.assertIsNone(claim_reply())
        save_reply(reply, 'failed', '部分回复', '出错了')
        url = f'{self.messages_url}{reply.pk}/retry/'
        self.assertEqual(self.client.post(url).status_code, 200)
        retried = claim_reply()
        self.assertEqual(retried.pk, reply.pk)
        self.assertGreater(retried.attempt, reply.attempt)
        self.assertFalse(save_reply(reply, 'completed', '迟到的旧结果'))
        save_reply(retried, 'completed', '新结果')
        self.assertEqual(self.client.post(url).status_code, 409)
        self.assertEqual(GroupMessage.objects.get(pk=reply.pk).content, '新结果')

    def test_provider_failure_and_stale_recovery(self):
        self.send()
        with patch('web.views.group_worker.ChatGraph.create_app', side_effect=RuntimeError('test failure')), patch('web.views.group_worker.logger'):
            self.assertTrue(process_next())
        reply = GroupMessage.objects.get(role='ai')
        self.assertEqual(reply.status, 'failed')
        self.assertTrue(reply.error)
        self.client.post(f'{self.messages_url}{reply.pk}/retry/')
        claimed = claim_reply()
        GroupMessage.objects.filter(pk=claimed.pk).update(update_time=now() - timedelta(minutes=6))
        recover_stale()
        self.assertEqual(GroupMessage.objects.get(pk=claimed.pk).status, 'failed')

    def test_group_deletion_and_fresh_heartbeat_survive_recovery_race(self):
        self.send()
        reply = claim_reply()
        stale_snapshot = GroupMessage.objects.get(pk=reply.pk)
        cutoff = now() - timedelta(minutes=5)
        self.assertFalse(save_reply(stale_snapshot, 'failed', '', stale_before=cutoff))
        self.assertEqual(GroupMessage.objects.get(pk=reply.pk).status, 'generating')
        self.group.delete()
        self.assertEqual(GroupMessage.objects.count(), 0)

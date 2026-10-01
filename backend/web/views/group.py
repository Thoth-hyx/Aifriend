import random
from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from web.models.character import Character
from web.models.friend import Friend
from web.models.group import ChatGroup, GroupMessage


def integer(value, name, minimum=1):
    try:
        if isinstance(value, bool):
            raise ValueError
        result = int(str(value))
        if result < minimum:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise ValidationError({'result': f'{name}无效'})


def character_data(character):
    return {'id': character.id, 'name': character.name, 'photo': character.photo.url}


def message_data(message):
    return {
        'id': message.id, 'group_id': message.group_id, 'role': message.role,
        'character_id': message.character_id, 'sender_name': message.sender_name,
        'sender_photo': message.character.photo.url if message.role == 'ai' and message.character and message.character.photo else '',
        'content': message.content, 'status': message.status,
        'client_message_id': str(message.client_message_id) if message.client_message_id else None,
        'reply_to': message.reply_to_id, 'revision': message.revision,
        'error': message.error, 'create_time': message.create_time.isoformat(),
    }


def group_data(group):
    latest = group.messages.select_related('character').order_by('-id').first()
    return {
        'id': group.id, 'name': group.name, 'revision': group.revision,
        'characters': [character_data(c) for c in group.characters.all()],
        'latest_message': message_data(latest) if latest else None,
        'update_time': group.update_time.isoformat(),
    }


def bump_revision(group_id):
    # Called inside a write transaction: SQLite serializes writers too.
    ChatGroup.objects.filter(pk=group_id).update(revision=F('revision') + 1, update_time=now())
    return ChatGroup.objects.values_list('revision', flat=True).get(pk=group_id)


def owned_group(request, group_id, write=False):
    if write:
        ChatGroup.objects.filter(pk=group_id, owner=request.user).update(revision=F('revision'))
    return get_object_or_404(ChatGroup, pk=group_id, owner=request.user)


class GroupListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        groups = ChatGroup.objects.filter(owner=request.user).prefetch_related('characters').order_by('-update_time', '-id')
        return Response({'result': 'success', 'groups': [group_data(g) for g in groups]})

    @transaction.atomic
    def post(self, request):
        name = request.data.get('name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 50:
            raise ValidationError({'result': '群聊名称需要为 1～50 个字'})
        group = ChatGroup.objects.create(owner=request.user, name=name.strip())
        return Response({'result': 'success', 'group': group_data(group)}, status=201)


class GroupCharacterView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, group_id):
        group = owned_group(request, group_id, write=True)
        character_id = integer(request.data.get('character_id'), '角色')
        if not Friend.objects.filter(me__user=request.user, character_id=character_id).exists():
            raise ValidationError({'result': '只能邀请好友列表中的 AI 角色'})
        character = get_object_or_404(Character, pk=character_id)
        group.characters.add(character)
        group.update_time = now()
        group.save(update_fields=['update_time'])
        return Response({'result': 'success', 'group': group_data(group)})

    @transaction.atomic
    def delete(self, request, group_id):
        group = owned_group(request, group_id, write=True)
        character_id = integer(request.data.get('character_id'), '角色')
        # Only remove the membership; Friend, Character and history stay intact.
        group.characters.remove(character_id)
        for message in group.messages.filter(character_id=character_id, role='ai', status__in=['pending', 'generating']):
            message.status = 'failed'
            message.error = '角色已移出群聊，回复已停止'
            message.revision = bump_revision(group.pk)
            message.update_time = now()
            message.save(update_fields=['status', 'error', 'revision', 'update_time'])
        group.update_time = now()
        group.save(update_fields=['update_time'])
        group.refresh_from_db(fields=['revision'])
        return Response({'result': 'success', 'group': group_data(group)})


class GroupMessageView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        group = owned_group(request, group_id)
        cursor = integer(request.query_params.get('after_revision', 0), '同步游标', minimum=0)
        if cursor > group.revision:
            raise ValidationError({'result': '同步游标已失效，请重新加载会话'})
        # Fix a high watermark. Later updates are fetched on the next request.
        messages = list(group.messages.select_related('character').filter(revision__gt=cursor, revision__lte=group.revision).order_by('revision', 'id')[:100])
        next_cursor = messages[-1].revision if len(messages) == 100 else group.revision
        return Response({
            'result': 'success', 'messages': [message_data(m) for m in messages],
            'cursor': next_cursor, 'has_more': next_cursor < group.revision,
        })

    @transaction.atomic
    def post(self, request, group_id):
        group = owned_group(request, group_id, write=True)
        content = request.data.get('content', '')
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= 2000:
            raise ValidationError({'result': '消息需要为 1～2000 个字'})
        content = content.strip()
        try:
            client_id = UUID(str(request.data.get('client_message_id', '')))
        except (ValueError, TypeError):
            raise ValidationError({'result': '消息标识无效'})
        target_id = request.data.get('character_id')
        target_id = integer(target_id, '角色') if target_id is not None else None
        previous = group.messages.filter(client_message_id=client_id).first()
        if previous:
            if previous.content != content or previous.character_id != target_id:
                return Response({'result': '同一消息标识不能用于不同内容'}, status=409)
            replies = group.messages.select_related('character').filter(reply_to=previous).order_by('id')
            return Response({'result': 'success', 'messages': [message_data(previous)] + [message_data(m) for m in replies]})
        characters = list(group.characters.all().order_by('id'))
        if not characters:
            raise ValidationError({'result': '请先从好友页面邀请 AI 角色'})
        character = next((c for c in characters if c.id == target_id), None) if target_id else random.choice(characters)
        if character is None:
            raise ValidationError({'result': '该角色不在群聊中'})
        user_message = GroupMessage.objects.create(
            group=group, role='user', character_id=target_id,
            sender_name=request.user.username, content=content,
            client_message_id=client_id, revision=bump_revision(group.pk),
        )
        reply = GroupMessage.objects.create(
            group=group, role='ai', character=character, sender_name=character.name,
            reply_to=user_message, status=GroupMessage.Status.PENDING,
            revision=bump_revision(group.pk),
        )
        return Response({'result': 'success', 'messages': [message_data(user_message), message_data(reply)]}, status=201)


class GroupRetryView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, group_id, message_id):
        group = owned_group(request, group_id, write=True)
        message = get_object_or_404(GroupMessage, pk=message_id, group=group, role='ai')
        if not message.character_id:
            raise ValidationError({'result': '角色已被删除，无法重试'})
        if not group.characters.filter(pk=message.character_id).exists():
            raise ValidationError({'result': '角色已移出群聊，请重新邀请后再重试'})
        revision = bump_revision(group.pk)
        changed = GroupMessage.objects.filter(pk=message.pk, status='failed').update(
            status='pending', content='', error='', revision=revision, update_time=now(),
        )
        if not changed:
            return Response({'result': '仅失败的回复可以重试'}, status=409)
        message.refresh_from_db()
        return Response({'result': 'success', 'message': message_data(message)})

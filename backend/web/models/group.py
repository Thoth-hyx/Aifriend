from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.timezone import now

from web.models.character import Character


class ChatGroup(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)
    characters = models.ManyToManyField(Character, blank=True)
    revision = models.PositiveBigIntegerField(default=0)
    create_time = models.DateTimeField(default=now)
    update_time = models.DateTimeField(default=now)

    def __str__(self):
        return self.name


class GroupMessage(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '等待回复'
        GENERATING = 'generating', '正在回复'
        COMPLETED = 'completed', '已完成'
        FAILED = 'failed', '回复失败'

    group = models.ForeignKey(ChatGroup, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=4, choices=[('user', '用户'), ('ai', 'AI')])
    character = models.ForeignKey(Character, null=True, blank=True, on_delete=models.SET_NULL)
    sender_name = models.CharField(max_length=150)
    content = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COMPLETED)
    client_message_id = models.UUIDField(null=True, blank=True)
    reply_to = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE)
    revision = models.PositiveBigIntegerField()
    attempt = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=200, blank=True)
    create_time = models.DateTimeField(default=now)
    update_time = models.DateTimeField(default=now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['group', 'client_message_id'], name='group_client_message_unique'),
            models.CheckConstraint(
                condition=Q(role='user', status='completed', client_message_id__isnull=False)
                | Q(role='ai', client_message_id__isnull=True, reply_to__isnull=False),
                name='group_message_role_state',
            ),
        ]
        indexes = [
            models.Index(fields=['group', 'revision']),
            models.Index(fields=['status', 'id']),
        ]

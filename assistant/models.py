"""Local conversation and explicit, single-object proposed changes.

Messages are retained until the owner deliberately exports or a future documented
retention feature is added. There is no automatic deletion job.
"""
import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q


class ChatSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assistant_sessions')
    title = models.CharField(max_length=120, default='新会话')
    submission_key = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-pk']
        indexes = [models.Index(fields=['owner', 'updated_at'], name='assist_session_owner_time')]


class Message(models.Model):
    class Role(models.TextChoices):
        USER = 'user', '用户'
        ASSISTANT = 'assistant', '助手'
        SYSTEM = 'system', '系统提示'

    class Status(models.TextChoices):
        SAVED = 'saved', '已本地保存'
        PROCESSING = 'processing', '等待处理'
        COMPLETED = 'completed', '已完成'
        NOT_CONNECTED = 'not_connected', 'AI 未连接'
        PROVIDER_ERROR = 'provider_error', '处理失败'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ChatSession, on_delete=models.PROTECT, related_name='messages')
    role = models.CharField(max_length=9, choices=Role.choices)
    text = models.TextField(max_length=20000, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SAVED)
    submission_key = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    request_hash = models.CharField(max_length=64, blank=True, editable=False)
    reply_to = models.OneToOneField('self', on_delete=models.PROTECT, related_name='response', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']
        indexes = [models.Index(fields=['session', 'created_at'], name='assist_message_session_time')]
        constraints = [
            models.CheckConstraint(condition=Q(role__in=['user', 'assistant', 'system']), name='assist_message_role_valid'),
            models.CheckConstraint(condition=Q(status__in=['saved', 'processing', 'completed', 'not_connected', 'provider_error']), name='assist_message_status_valid'),
        ]


class MessageAttachment(models.Model):
    message = models.ForeignKey(Message, on_delete=models.PROTECT, related_name='image_links')
    attachment = models.ForeignKey('attachments.Attachment', on_delete=models.PROTECT, related_name='message_links')
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position', 'pk']
        constraints = [models.UniqueConstraint(fields=['message', 'attachment'], name='assist_message_attachment_uq')]


class Draft(models.Model):
    class Operation(models.TextChoices):
        CREATE_QUESTION = 'create_question', '新增错题'
        UPDATE_QUESTION = 'update_question', '修改指定错题'
        UPDATE_TASK = 'update_task', '修改指定任务'

    class Status(models.TextChoices):
        PENDING = 'pending', '待确认'
        APPLIED = 'applied', '已确认保存'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assistant_drafts')
    session = models.ForeignKey(ChatSession, on_delete=models.PROTECT, related_name='drafts')
    source_message = models.ForeignKey(Message, on_delete=models.PROTECT, related_name='drafts', null=True, blank=True)
    operation = models.CharField(max_length=20, choices=Operation.choices)
    title = models.CharField(max_length=180)
    payload = models.JSONField()
    before_snapshot = models.JSONField(default=dict, blank=True)
    after_snapshot = models.JSONField(default=dict)
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    expected_version = models.TextField(blank=True)
    submission_key = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    request_hash = models.CharField(max_length=64, editable=False)
    status = models.CharField(max_length=7, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    confirmation_key = models.UUIDField(unique=True, null=True, blank=True, editable=False)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['owner', 'status', 'created_at'], name='assist_draft_owner_status')]
        constraints = [
            models.CheckConstraint(condition=Q(operation__in=['create_question', 'update_question', 'update_task']), name='assist_draft_operation_valid'),
            models.CheckConstraint(condition=(Q(status='pending', applied_at__isnull=True, applied_object_id__isnull=True, confirmation_key__isnull=True) | Q(status='applied', applied_at__isnull=False, applied_object_id__isnull=False, confirmation_key__isnull=False)), name='assist_draft_application_valid'),
        ]

"""Immutable private image content and independently frozen review relationships."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class ImageRole(models.TextChoices):
    QUESTION = 'question', '题干'
    ORIGINAL_ANSWER = 'original_answer', '原答'
    CORRECT_ANSWER = 'correct_answer', '参考答案'
    ERROR_REASON = 'error_reason', '错因'


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('已保存的图片和历史快照不可修改。')

    def bulk_update(self, *args, **kwargs):
        raise ValidationError('已保存的图片和历史快照不可修改。')

    def delete(self):
        raise ValidationError('图片及历史快照不提供删除。')


class ImmutableModel(models.Model):
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('已保存的图片和历史快照不可修改。')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('图片及历史快照不提供删除。')


class Attachment(ImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='image_attachments')
    display_name = models.CharField(max_length=200)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=80, unique=True, editable=False)
    byte_size = models.PositiveBigIntegerField()
    thumbnail_bytes = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['owner', 'sha256'], name='attachment_owner_sha_uq'),
            models.CheckConstraint(condition=Q(width__gte=1, width__lte=10000, height__gte=1, height__lte=10000), name='attachment_dimensions_valid'),
        ]
        indexes = [models.Index(fields=['owner', 'created_at'], name='attachment_owner_time_idx')]

    def __str__(self):
        return self.display_name


class QuestionImage(models.Model):
    question = models.ForeignKey('learning.WrongQuestion', on_delete=models.PROTECT, related_name='image_links')
    attachment = models.ForeignKey(Attachment, on_delete=models.PROTECT, related_name='question_links')
    role = models.CharField(max_length=16, choices=ImageRole.choices, default=ImageRole.QUESTION)
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['role', 'position', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['question', 'role', 'position'], name='question_image_position_uq'),
            models.UniqueConstraint(fields=['question', 'role', 'attachment'], name='question_image_attachment_uq'),
            models.CheckConstraint(condition=Q(role__in=ImageRole.values), name='question_image_role_valid'),
        ]

    def clean(self):
        if self.question_id and self.attachment_id and self.question.course.owner_id != self.attachment.owner_id:
            raise ValidationError('图片必须属于错题的所有者。')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ReviewImageManifest(ImmutableModel):
    """An empty manifest freezes the absence of images too."""
    review = models.OneToOneField('learning.ReviewRecord', on_delete=models.PROTECT, primary_key=True, related_name='image_manifest')
    image_count = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


class ReviewImageSnapshot(ImmutableModel):
    review = models.ForeignKey('learning.ReviewRecord', on_delete=models.PROTECT, related_name='image_snapshots')
    attachment = models.ForeignKey(Attachment, on_delete=models.PROTECT, related_name='review_snapshots')
    role = models.CharField(max_length=16, choices=ImageRole.choices)
    position = models.PositiveSmallIntegerField()
    name_snapshot = models.CharField(max_length=200)
    width_snapshot = models.PositiveIntegerField()
    height_snapshot = models.PositiveIntegerField()
    sha256_snapshot = models.CharField(max_length=64)

    class Meta:
        ordering = ['role', 'position', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['review', 'role', 'position'], name='review_image_position_uq'),
            models.UniqueConstraint(fields=['review', 'role', 'attachment'], name='review_image_attachment_uq'),
            models.CheckConstraint(condition=Q(role__in=ImageRole.values), name='review_image_role_valid'),
        ]

    def clean(self):
        if self.review_id and self.attachment_id and self.review.question.course.owner_id != self.attachment.owner_id:
            raise ValidationError('历史图片必须属于复习记录的所有者。')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

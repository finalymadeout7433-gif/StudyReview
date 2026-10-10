from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from .engine import (ALGORITHM, ALGORITHM_VERSION, CONFIG_VERSION,
                     validate_card_state, validate_metadata)


class SchedulingState(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name='scheduling_states')
    question = models.ForeignKey('learning.WrongQuestion', on_delete=models.PROTECT,
                                 related_name='scheduling_states')
    algorithm = models.CharField(max_length=16, default=ALGORITHM)
    algorithm_version = models.CharField(max_length=20, default=ALGORITHM_VERSION)
    config_version = models.CharField(max_length=40, default=CONFIG_VERSION)
    config_snapshot = models.JSONField()
    card_state = models.JSONField()
    revision = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'question'],
                                               name='schedule_user_question_uq')]

    def clean(self):
        super().clean()
        if self.question_id and self.user_id and self.question.course.owner_id != self.user_id:
            raise ValidationError('复习算法状态必须属于题目所有者。')
        validate_metadata(self.algorithm, self.algorithm_version,
                          self.config_version, self.config_snapshot)
        validate_card_state(self.card_state, self.question_id)
        if (self.revision == 0) != (self.card_state['last_review'] is None):
            raise ValidationError('复习算法状态与修订号不匹配。')


class ImmutableScheduleQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('调度历史不可修改。')

    def delete(self):
        raise ValidationError('调度历史不可删除。')

    def bulk_update(self, *args, **kwargs):
        raise ValidationError('调度历史不可修改。')


class ScheduleEvent(models.Model):
    state = models.ForeignKey(SchedulingState, on_delete=models.PROTECT,
                              related_name='events')
    review_record = models.OneToOneField('learning.ReviewRecord', on_delete=models.PROTECT,
                                        related_name='schedule_event')
    algorithm = models.CharField(max_length=16)
    algorithm_version = models.CharField(max_length=20)
    config_version = models.CharField(max_length=40)
    config_snapshot = models.JSONField()
    state_revision_before = models.PositiveBigIntegerField()
    state_revision_after = models.PositiveBigIntegerField()
    before_state = models.JSONField()
    after_state = models.JSONField()
    fsrs_review_log = models.JSONField()
    reviewed_at = models.DateTimeField()
    review_date = models.DateField()
    due_utc = models.DateTimeField()
    suggested_date = models.DateField()
    applied_date = models.DateField()
    manual_override_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableScheduleQuerySet.as_manager()

    class Meta:
        ordering = ['-reviewed_at', '-pk']
        indexes = [models.Index(fields=['state', 'reviewed_at'], name='schedule_event_time_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(state_revision_after=F('state_revision_before') + 1),
                                   name='schedule_revision_increments'),
            models.CheckConstraint(condition=Q(due_utc__gt=F('reviewed_at')),
                                   name='schedule_due_after_review'),
            models.CheckConstraint(condition=Q(suggested_date__gt=F('review_date')),
                                   name='schedule_suggestion_future'),
            models.CheckConstraint(condition=Q(applied_date__gt=F('review_date')),
                                   name='schedule_applied_future'),
            models.CheckConstraint(condition=(Q(manual_override_date__isnull=True,
                                                 applied_date=F('suggested_date'))
                                              | Q(manual_override_date__isnull=False,
                                                  manual_override_date=F('applied_date'))),
                                   name='schedule_override_consistent'),
        ]

    def clean(self):
        super().clean()
        validate_metadata(self.algorithm, self.algorithm_version,
                          self.config_version, self.config_snapshot)
        if self.state_id and self.review_record_id:
            if self.state.question_id != self.review_record.question_id:
                raise ValidationError('调度记录与复习题目不匹配。')
            if self.state.user_id != self.review_record.question.course.owner_id:
                raise ValidationError('调度记录与题目所有者不匹配。')
            validate_card_state(self.before_state, self.state.question_id)
            validate_card_state(self.after_state, self.state.question_id)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('调度历史不可修改。')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('调度历史不可删除。')

"""Caller must hold course then question locks; state is always locked last.

The caller saves ReviewRecord and question.next_review_date in the SAME atomic
transaction. These helpers never change legacy snapshots or question due dates.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.http import Http404
from django.utils import timezone

from learning.models import WrongQuestion
from .engine import (ALGORITHM, ALGORITHM_VERSION, CONFIG_VERSION, SHANGHAI,
                     ScheduleStateError, calculate, initial_card, scheduler_config,
                     utc_datetime, validate_card_state, validate_metadata)
from .models import ScheduleEvent, SchedulingState


@dataclass(frozen=True)
class ScheduleProposal:
    user_id: int
    question_id: int
    state_id: int | None
    expected_revision: int
    rating: str
    reviewed_at: datetime
    due_utc: datetime
    due_date: date
    before_state: dict
    after_state: dict
    review_log: dict
    config_snapshot: dict
    algorithm: str = ALGORITHM
    algorithm_version: str = ALGORITHM_VERSION
    config_version: str = CONFIG_VERSION
    cold_start: bool = False
    database_alias: str = 'default'

    @property
    def explanation(self):
        introduction = '从本次真实复习开始建立状态；旧历史未重放。' if self.cold_start else '根据本题已保存的复习状态计算。'
        return (f'FSRS {self.algorithm_version} · {int(self.config_snapshot["desired_retention"] * 100)}% '
                f'目标保留率；{int((self.due_date - self.reviewed_at.astimezone(SHANGHAI).date()).days)} '
                f'天后复习。{introduction}这是算法建议，不保证记忆效果；可手动调整日期。')


def _owned_question(user, question, writable=False):
    if not getattr(user, 'is_authenticated', False) or not user.pk or not question.pk:
        raise Http404()
    alias = question._state.db or 'default'
    try:
        current = WrongQuestion.objects.using(alias).select_related('course').get(
            pk=question.pk, course__owner_id=user.pk)
    except WrongQuestion.DoesNotExist as exc:
        raise Http404() from exc
    if writable and (current.is_archived or current.course.is_archived):
        raise ValidationError('已归档内容不能提交复习。')
    return current, alias


def _require_atomic(alias):
    if not connections[alias].in_atomic_block:
        raise RuntimeError('Scheduling writes require the caller course/question atomic transaction.')


def _validate_state(state):
    validate_metadata(state.algorithm, state.algorithm_version,
                      state.config_version, state.config_snapshot)
    validate_card_state(state.card_state, state.question_id)
    if (state.revision == 0) != (state.card_state['last_review'] is None):
        raise ScheduleStateError('复习算法状态修订号不一致；本次未保存。')


def _proposal(user, question, state, rating, reviewed_at, alias):
    if state is None:
        before, revision, state_id = initial_card(question.pk, reviewed_at), 0, None
    else:
        _validate_state(state)
        before, revision, state_id = deepcopy(state.card_state), state.revision, state.pk
    result = calculate(before, question.pk, rating, reviewed_at)
    return ScheduleProposal(user.pk, question.pk, state_id, revision, rating,
                            result.reviewed_at, result.due_utc, result.due_date,
                            result.before_state, result.after_state, result.review_log,
                            result.config_snapshot, cold_start=revision == 0,
                            database_alias=alias)


def schedule_revision(user, question):
    """Include in a signed page version; absence is revision zero, not a write."""
    current, alias = _owned_question(user, question)
    value = SchedulingState.objects.using(alias).filter(user_id=user.pk, question=current).values_list(
        'revision', flat=True).first()
    return value if value is not None else 0


def suggest_schedule(user, question, rating, reviewed_at=None):
    """Read-only preview. The signed submission must calculate again under locks."""
    reviewed_at = utc_datetime(reviewed_at or timezone.now())
    current, alias = _owned_question(user, question, writable=True)
    state = SchedulingState.objects.using(alias).filter(user_id=user.pk, question=current).first()
    return _proposal(user, current, state, rating, reviewed_at, alias)


def prepare_schedule(user, question, rating, reviewed_at):
    """Only after the caller locks course and question, in that order."""
    current, alias = _owned_question(user, question, writable=True)
    _require_atomic(alias)
    reviewed_at = utc_datetime(reviewed_at)
    # Compute/validate the first candidate before creating any persistent state.
    initial = initial_card(current.pk, reviewed_at)
    manager = SchedulingState.objects.using(alias).select_for_update()
    state, _created = manager.get_or_create(user_id=user.pk, question=current, defaults={
        'card_state': initial, 'config_snapshot': scheduler_config(),
        'algorithm': ALGORITHM, 'algorithm_version': ALGORITHM_VERSION,
        'config_version': CONFIG_VERSION,
    })
    return _proposal(user, current, state, rating, reviewed_at, alias)


def commit_schedule(proposal, review_record, user_override_date=None):
    """Atomic state + immutable event; the caller also updates the question due."""
    if not isinstance(proposal, ScheduleProposal) or proposal.state_id is None:
        raise ValidationError('请先在复习事务中准备调度方案。')
    alias = proposal.database_alias
    _require_atomic(alias)
    if not review_record.pk or review_record._state.adding or review_record._state.db != alias:
        raise ValidationError('请先在同一数据库事务中保存复习记录。')
    if user_override_date is not None and (not isinstance(user_override_date, date)
                                          or isinstance(user_override_date, datetime)):
        raise ValidationError({'next_review_date': '手动改期必须是有效日期。'})
    applied_date = user_override_date or proposal.due_date
    review_date = proposal.reviewed_at.astimezone(SHANGHAI).date()
    if applied_date <= review_date:
        raise ValidationError({'next_review_date': '下次复习必须晚于本次复习日期。'})
    if (review_record.question_id != proposal.question_id or review_record.rating != proposal.rating
            or review_record.review_date != review_date
            or utc_datetime(review_record.reviewed_at) != proposal.reviewed_at
            or review_record.next_review_date != applied_date):
        raise ValidationError('复习快照与调度方案不匹配，本次未保存。')
    validate_metadata(proposal.algorithm, proposal.algorithm_version,
                      proposal.config_version, proposal.config_snapshot)
    with transaction.atomic(using=alias):
        state = SchedulingState.objects.using(alias).select_for_update().get(pk=proposal.state_id)
        if state.user_id != proposal.user_id or state.question_id != proposal.question_id:
            raise Http404()
        current = WrongQuestion.objects.using(alias).select_related('course').get(pk=state.question_id)
        if current.course.owner_id != proposal.user_id:
            raise Http404()
        if current.is_archived or current.course.is_archived:
            raise ValidationError('已归档内容不能提交复习。')
        existing = ScheduleEvent.objects.using(alias).filter(review_record=review_record).first()
        if existing is not None:
            if (existing.state_id != state.pk or existing.state_revision_before != proposal.expected_revision
                    or existing.before_state != proposal.before_state or existing.after_state != proposal.after_state
                    or existing.applied_date != applied_date or existing.manual_override_date != user_override_date):
                raise ValidationError('已保存的调度记录与本次提交不匹配。')
            return existing
        _validate_state(state)
        if state.revision != proposal.expected_revision or state.card_state != proposal.before_state:
            raise ValidationError('复习算法状态已更新，请重新进入复习。', code='schedule_stale')
        result = calculate(state.card_state, state.question_id, proposal.rating, proposal.reviewed_at)
        if (result.after_state != proposal.after_state or result.review_log != proposal.review_log
                or result.due_utc != proposal.due_utc or result.due_date != proposal.due_date):
            raise ValidationError('调度方案校验失败，本次未保存。')
        event = ScheduleEvent(
            state=state, review_record=review_record, algorithm=proposal.algorithm,
            algorithm_version=proposal.algorithm_version, config_version=proposal.config_version,
            config_snapshot=deepcopy(proposal.config_snapshot),
            state_revision_before=state.revision, state_revision_after=state.revision + 1,
            before_state=deepcopy(proposal.before_state), after_state=deepcopy(proposal.after_state),
            fsrs_review_log=deepcopy(proposal.review_log), reviewed_at=proposal.reviewed_at,
            review_date=review_date, due_utc=proposal.due_utc, suggested_date=proposal.due_date,
            applied_date=applied_date, manual_override_date=user_override_date)
        event.full_clean()
        event.save(using=alias)
        state.card_state = deepcopy(proposal.after_state)
        state.revision += 1
        state.full_clean()
        state.save(using=alias, update_fields=['card_state', 'revision', 'updated_at'])
        return event

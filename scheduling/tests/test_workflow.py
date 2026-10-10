from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.http import Http404
from django.test import TestCase, override_settings

from learning.models import Course, ReviewRecord, WrongQuestion
from scheduling.engine import SHANGHAI, ScheduleStateError
from scheduling.models import ScheduleEvent, SchedulingState
from scheduling import services

NOW = datetime(2026, 10, 3, 15, 50, tzinfo=datetime_timezone.utc)


def save_review(question, proposal, next_date=None, submission_key=None):
    record = ReviewRecord(
        question=question, reviewed_at=proposal.reviewed_at,
        review_date=proposal.reviewed_at.astimezone(SHANGHAI).date(),
        answer='Synthetic independent answer', rating=proposal.rating, note='',
        next_review_date=next_date or proposal.due_date,
        title_snapshot=question.title, question_snapshot=question.content,
        original_answer_snapshot=question.original_answer,
        correct_answer_snapshot=question.correct_answer,
        error_reason_snapshot=question.error_reason, course_snapshot=question.course.name,
        knowledge_points_snapshot=[], submission_key=submission_key or uuid.uuid4())
    record.full_clean()
    record.save()
    return record


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SchedulingWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('fsrs_synthetic_owner', password='synthetic-fsrs-2026!')
        self.other = User.objects.create_user('fsrs_synthetic_other')
        self.course = Course.objects.create(owner=self.user, name='Synthetic FSRS course')
        self.question = WrongQuestion.objects.create(
            course=self.course, title='Synthetic question', content='Synthetic question body',
            original_answer='old', correct_answer='correct', error_reason='test only',
            next_review_date=NOW.astimezone(SHANGHAI).date() - timedelta(days=10))

    def locked_proposal(self, rating='good', reviewed_at=NOW):
        Course.objects.select_for_update().get(pk=self.course.pk)
        question = WrongQuestion.objects.select_for_update().select_related('course').get(pk=self.question.pk)
        return question, services.prepare_schedule(self.user, question, rating, reviewed_at)

    def submit(self, rating='good', reviewed_at=NOW, override=None, key=None):
        with transaction.atomic():
            question, proposal = self.locked_proposal(rating, reviewed_at)
            record = save_review(question, proposal, override, key)
            event = services.commit_schedule(proposal, record, override)
            question.next_review_date = record.next_review_date
            question.save(update_fields=['next_review_date', 'updated_at'])
            return record, event, proposal

    def test_suggestion_does_not_create_state_or_change_existing_due(self):
        original_date = self.question.next_review_date
        for rating in ('again', 'hard', 'good'):
            proposal = services.suggest_schedule(self.user, self.question, rating, NOW)
            self.assertTrue(proposal.cold_start)
            self.assertIsNone(proposal.state_id)
            self.assertIn('旧历史未重放', proposal.explanation)
        self.assertEqual(SchedulingState.objects.count(), 0)
        self.assertEqual(ScheduleEvent.objects.count(), 0)
        self.assertEqual(ReviewRecord.objects.count(), 0)
        self.question.refresh_from_db()
        self.assertEqual(self.question.next_review_date, original_date)

    def test_legacy_history_is_preserved_and_never_replayed(self):
        legacy_time = NOW - timedelta(days=20)
        legacy_proposal = services.suggest_schedule(self.user, self.question, 'hard', legacy_time)
        legacy = save_review(self.question, legacy_proposal,
                             legacy_time.astimezone(SHANGHAI).date() + timedelta(days=3))
        original = deepcopy(legacy.__dict__)
        record, event, proposal = self.submit('good')
        legacy.refresh_from_db()
        self.assertEqual(legacy.rating, original['rating'])
        self.assertEqual(legacy.next_review_date, original['next_review_date'])
        self.assertFalse(ScheduleEvent.objects.filter(review_record=legacy).exists())
        self.assertEqual(event.before_state['last_review'], None)
        self.assertEqual(event.state_revision_after, 1)
        self.assertEqual(ReviewRecord.objects.count(), 2)

    def test_commit_persists_versioned_state_and_immutable_event(self):
        record, event, proposal = self.submit('good')
        state = SchedulingState.objects.get()
        self.assertEqual(state.user, self.user)
        self.assertEqual(state.question, self.question)
        self.assertEqual(state.revision, 1)
        self.assertEqual(state.card_state, proposal.after_state)
        self.assertEqual(event.review_record, record)
        self.assertEqual(event.algorithm_version, '6.3.2')
        self.assertEqual(event.config_version, 'shanghai-daily-v1')
        self.assertEqual(len(event.config_snapshot['parameters']), 21)
        self.assertEqual(event.due_utc, proposal.due_utc)
        self.assertEqual(event.suggested_date, proposal.due_date)
        self.assertIsNone(event.manual_override_date)
        self.question.refresh_from_db()
        self.assertEqual(self.question.next_review_date, event.applied_date)

    def test_manual_override_preserves_exact_algorithm_due_and_both_dates(self):
        override = NOW.astimezone(SHANGHAI).date() + timedelta(days=30)
        record, event, proposal = self.submit('hard', override=override)
        self.assertEqual(record.next_review_date, override)
        self.assertEqual(event.manual_override_date, override)
        self.assertEqual(event.applied_date, override)
        self.assertEqual(event.suggested_date, proposal.due_date)
        self.assertNotEqual(event.suggested_date, override)
        self.assertEqual(event.after_state['due'], proposal.due_utc.isoformat())

    def test_commit_replay_is_idempotent_and_does_not_advance_state(self):
        record, event, proposal = self.submit()
        repeated = services.commit_schedule(proposal, record)
        self.assertEqual(repeated.pk, event.pk)
        self.assertEqual(ScheduleEvent.objects.count(), 1)
        self.assertEqual(SchedulingState.objects.get().revision, 1)

    def test_stale_second_proposal_rolls_back_its_new_record(self):
        with transaction.atomic():
            question, first = self.locked_proposal()
            question, stale = self.locked_proposal()
            record = save_review(question, first)
            services.commit_schedule(first, record)
            with self.assertRaises(ValidationError):
                with transaction.atomic():
                    second = save_review(question, stale)
                    services.commit_schedule(stale, second)
        self.assertEqual(ReviewRecord.objects.count(), 1)
        self.assertEqual(ScheduleEvent.objects.count(), 1)
        self.assertEqual(SchedulingState.objects.get().revision, 1)

    def test_failure_after_event_insert_rolls_back_record_event_and_state(self):
        original_due = self.question.next_review_date
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                question, proposal = self.locked_proposal()
                record = save_review(question, proposal)
                with patch.object(SchedulingState, 'save', side_effect=RuntimeError('synthetic state failure')):
                    services.commit_schedule(proposal, record)
        self.assertEqual(ReviewRecord.objects.count(), 0)
        self.assertEqual(ScheduleEvent.objects.count(), 0)
        self.assertEqual(SchedulingState.objects.count(), 0)
        self.question.refresh_from_db()
        self.assertEqual(self.question.next_review_date, original_due)

    def test_question_update_failure_rolls_back_entire_root_transaction(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                question, proposal = self.locked_proposal()
                record = save_review(question, proposal)
                services.commit_schedule(proposal, record)
                with patch.object(WrongQuestion, 'save', side_effect=RuntimeError('synthetic due update failure')):
                    question.next_review_date = record.next_review_date
                    question.save(update_fields=['next_review_date', 'updated_at'])
        self.assertEqual(ReviewRecord.objects.count(), 0)
        self.assertEqual(ScheduleEvent.objects.count(), 0)
        self.assertEqual(SchedulingState.objects.count(), 0)

    def test_corrupt_state_reports_error_without_reset_or_due_change(self):
        self.submit()
        state = SchedulingState.objects.get()
        SchedulingState.objects.filter(pk=state.pk).update(card_state={'corrupt': True})
        self.question.refresh_from_db()
        due = self.question.next_review_date
        with self.assertRaises(ScheduleStateError):
            services.suggest_schedule(self.user, self.question, 'good', NOW + timedelta(days=5))
        with self.assertRaises(ScheduleStateError):
            with transaction.atomic():
                self.locked_proposal('good', NOW + timedelta(days=5))
        state.refresh_from_db()
        self.assertEqual(state.card_state, {'corrupt': True})
        self.assertEqual(state.revision, 1)
        self.assertEqual(ScheduleEvent.objects.count(), 1)
        self.question.refresh_from_db()
        self.assertEqual(self.question.next_review_date, due)

    def test_unsupported_state_version_is_not_silently_upgraded(self):
        self.submit()
        SchedulingState.objects.update(algorithm_version='5.0.0')
        with self.assertRaises(ScheduleStateError):
            services.suggest_schedule(self.user, self.question, 'good', NOW + timedelta(days=5))
        self.assertEqual(SchedulingState.objects.get().algorithm_version, '5.0.0')

    def test_foreign_user_cannot_preview_prepare_or_read_revision(self):
        for operation in (lambda: services.suggest_schedule(self.other, self.question, 'good', NOW),
                          lambda: services.prepare_schedule(self.other, self.question, 'good', NOW),
                          lambda: services.schedule_revision(self.other, self.question)):
            with self.assertRaises(Http404):
                operation()
        self.assertEqual(SchedulingState.objects.count(), 0)

    def test_archived_course_or_question_cannot_schedule(self):
        Course.objects.filter(pk=self.course.pk).update(is_archived=True)
        with self.assertRaises(ValidationError):
            services.prepare_schedule(self.user, self.question, 'good', NOW)
        Course.objects.filter(pk=self.course.pk).update(is_archived=False)
        WrongQuestion.objects.filter(pk=self.question.pk).update(is_archived=True)
        with self.assertRaises(ValidationError):
            services.suggest_schedule(self.user, self.question, 'good', NOW)
        self.assertEqual(SchedulingState.objects.count(), 0)

    def test_archive_between_prepare_and_commit_is_rejected(self):
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                question, proposal = self.locked_proposal()
                record = save_review(question, proposal)
                Course.objects.filter(pk=self.course.pk).update(is_archived=True)
                services.commit_schedule(proposal, record)
        self.assertEqual(SchedulingState.objects.count(), 0)
        self.assertEqual(ScheduleEvent.objects.count(), 0)

    def test_prepare_requires_atomic_transaction(self):
        with patch('scheduling.services._owned_question', return_value=(self.question, 'default')):
            with patch('scheduling.services.connections', {'default': SimpleNamespace(in_atomic_block=False)}):
                with self.assertRaises(RuntimeError):
                    services.prepare_schedule(self.user, self.question, 'good', NOW)

    def test_readonly_suggestion_cannot_be_committed(self):
        proposal = services.suggest_schedule(self.user, self.question, 'good', NOW)
        record = save_review(self.question, proposal)
        with self.assertRaises(ValidationError):
            services.commit_schedule(proposal, record)
        self.assertEqual(ScheduleEvent.objects.count(), 0)

    def test_invalid_manual_override_types_or_past_dates_are_rejected(self):
        question, proposal = self.locked_proposal()
        record = save_review(question, proposal)
        for override in (NOW, '2027-01-01', NOW.astimezone(SHANGHAI).date(),
                         NOW.astimezone(SHANGHAI).date() - timedelta(days=1)):
            with self.subTest(override=override), self.assertRaises(ValidationError):
                services.commit_schedule(proposal, record, override)
        self.assertEqual(ScheduleEvent.objects.count(), 0)
        self.assertEqual(SchedulingState.objects.get().revision, 0)

    def test_record_clock_or_rating_mismatch_is_rejected(self):
        question, proposal = self.locked_proposal()
        for modified in (replace(proposal, reviewed_at=NOW + timedelta(seconds=1)),
                         replace(proposal, rating='again')):
            with self.subTest(modified=modified.rating):
                record = save_review(question, modified)
                with self.assertRaises(ValidationError):
                    services.commit_schedule(proposal, record)
        self.assertEqual(ScheduleEvent.objects.count(), 0)

    def test_mutated_proposal_is_recomputed_and_rejected(self):
        question, proposal = self.locked_proposal()
        tampered = replace(proposal, after_state={**proposal.after_state, 'stability': 99.0})
        record = save_review(question, proposal)
        with self.assertRaises(ValidationError):
            services.commit_schedule(tampered, record)
        self.assertEqual(ScheduleEvent.objects.count(), 0)
        self.assertEqual(SchedulingState.objects.get().revision, 0)

    def test_state_user_question_unique_constraint_is_enforced(self):
        question, proposal = self.locked_proposal()
        state = SchedulingState.objects.get()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SchedulingState.objects.create(user=self.user, question=question,
                                               card_state=state.card_state,
                                               config_snapshot=state.config_snapshot)

    def test_model_validation_rejects_foreign_owner_state(self):
        question, proposal = self.locked_proposal()
        state = SchedulingState.objects.get()
        state.user = self.other
        with self.assertRaises(ValidationError):
            state.full_clean()

    def test_schedule_revision_changes_only_after_commit(self):
        self.assertEqual(services.schedule_revision(self.user, self.question), 0)
        question, proposal = self.locked_proposal()
        self.assertEqual(services.schedule_revision(self.user, question), 0)
        record = save_review(question, proposal)
        services.commit_schedule(proposal, record)
        self.assertEqual(services.schedule_revision(self.user, question), 1)

    def test_events_cannot_be_changed_or_deleted_through_orm(self):
        record, event, proposal = self.submit()
        for operation in (lambda: event.save(), lambda: event.delete(),
                          lambda: ScheduleEvent.objects.update(applied_date=proposal.due_date),
                          lambda: ScheduleEvent.objects.all().delete(),
                          lambda: ScheduleEvent.objects.bulk_update([event], ['applied_date'])):
            with self.assertRaises(ValidationError):
                operation()
        self.assertEqual(ScheduleEvent.objects.count(), 1)

    def test_mysql_triggers_block_raw_event_update_and_delete(self):
        if connection.vendor != 'mysql':
            self.skipTest('Database trigger acceptance requires MySQL.')
        record, event, proposal = self.submit()
        for sql in ('UPDATE scheduling_scheduleevent SET applied_date=applied_date WHERE id=%s',
                    'DELETE FROM scheduling_scheduleevent WHERE id=%s'):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(sql, [event.pk])
        self.assertEqual(ScheduleEvent.objects.count(), 1)

    def test_database_rejects_date_change_without_explicit_override_even_when_null(self):
        record, event, proposal = self.submit()
        changed_date = proposal.due_date + timedelta(days=5)
        second_record = save_review(self.question, proposal, changed_date)
        values = {field.attname: getattr(event, field.attname)
                  for field in ScheduleEvent._meta.concrete_fields
                  if not field.primary_key and field.name != 'created_at'}
        values.update(review_record_id=second_record.pk, applied_date=changed_date,
                      manual_override_date=None)
        # SQL CHECK permits UNKNOWN; IS NOT NULL must be explicit in its second branch.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ScheduleEvent.objects.create(**values)
        self.assertEqual(ScheduleEvent.objects.count(), 1)

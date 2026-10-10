"""Root review service + FSRS + private image snapshots, synthetic data only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
import uuid

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import F
from django.http import Http404
from django.test import TestCase, override_settings

from attachments.models import Attachment, ImageRole, QuestionImage, ReviewImageManifest, ReviewImageSnapshot
from learning import services
from learning.models import Course, ReviewRecord, WrongQuestion
from scheduling.engine import SHANGHAI, ScheduleStateError
from scheduling.models import ScheduleEvent, SchedulingState

NOW = datetime(2026, 10, 3, 15, 50, tzinfo=dt_timezone.utc)
TODAY = NOW.astimezone(SHANGHAI).date()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class V2ReviewScheduleIntegrationTests(TestCase):
    def setUp(self):
        clock = patch('learning.services.timezone.now', return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.user = User.objects.create_user('v2_integrated_owner')
        self.other = User.objects.create_user('v2_integrated_other')
        self.course = Course.objects.create(owner=self.user, name='Synthetic integrated course')
        self.question = WrongQuestion.objects.create(
            course=self.course, title='Synthetic integrated question', content='Original synthetic question',
            original_answer='Old synthetic answer', correct_answer='Correct synthetic answer',
            error_reason='Synthetic reasoning', next_review_date=TODAY)
        self.attachment = Attachment.objects.create(
            owner=self.user, display_name='synthetic-database-fixture.png', width=64, height=48,
            sha256='a' * 64, storage_key='ab/' + uuid.uuid4().hex,
            byte_size=100, thumbnail_bytes=100)
        QuestionImage.objects.create(question=self.question, attachment=self.attachment,
                                     role=ImageRole.QUESTION, position=0)

    def token(self):
        self.question.refresh_from_db()
        return services.reveal_token(services.make_token(self.user, 'review', self.question),
                                     self.user, self.question)

    def submit(self, rating='hard', token=None, **values):
        return services.submit_review(self.user, self.question.pk,
                                      {'answer': 'Independent synthetic response', 'rating': rating, **values},
                                      token or self.token())

    def assert_no_partial_review(self):
        self.assertEqual(ReviewRecord.objects.count(), 0)
        self.assertEqual(SchedulingState.objects.count(), 0)
        self.assertEqual(ScheduleEvent.objects.count(), 0)
        self.assertEqual(ReviewImageManifest.objects.count(), 0)
        self.assertEqual(ReviewImageSnapshot.objects.count(), 0)
        self.question.refresh_from_db()
        self.assertEqual(self.question.next_review_date, TODAY)

    def test_real_service_persists_one_atomic_review_image_and_schedule(self):
        record, created = self.submit('hard')
        self.assertTrue(created)
        event = ScheduleEvent.objects.get(review_record=record)
        state = SchedulingState.objects.get(question=self.question, user=self.user)
        self.assertEqual(record.reviewed_at, NOW)
        self.assertEqual(event.reviewed_at, NOW)
        self.assertEqual(record.review_date, TODAY)
        self.assertEqual(record.next_review_date, TODAY + timedelta(days=1))
        self.assertEqual(event.applied_date, record.next_review_date)
        self.assertEqual(event.after_state, state.card_state)
        self.assertEqual(state.revision, 1)
        self.assertEqual(record.image_manifest.image_count, 1)
        self.assertEqual(record.image_snapshots.get().attachment_id, self.attachment.pk)
        self.question.refresh_from_db()
        self.assertEqual(self.question.next_review_date, record.next_review_date)

    def test_empty_image_set_is_also_frozen_in_same_transaction(self):
        self.question.image_links.all().delete()
        record, _ = self.submit()
        self.assertEqual(record.image_manifest.image_count, 0)
        self.assertEqual(record.image_snapshots.count(), 0)
        self.assertEqual(ScheduleEvent.objects.filter(review_record=record).count(), 1)

    def test_same_signed_submission_replay_does_not_advance_or_append_images(self):
        token = self.token()
        record, _ = self.submit(token=token)
        original_card = deepcopy(SchedulingState.objects.get().card_state)
        self.question.image_links.all().delete()
        repeated, created = self.submit('good', token=token, answer='Different replay payload')
        self.assertFalse(created)
        self.assertEqual(repeated.pk, record.pk)
        self.assertEqual(repeated.rating, 'hard')
        self.assertEqual(ReviewRecord.objects.count(), 1)
        self.assertEqual(SchedulingState.objects.get().revision, 1)
        self.assertEqual(SchedulingState.objects.get().card_state, original_card)
        self.assertEqual(ScheduleEvent.objects.count(), 1)
        self.assertEqual(ReviewImageManifest.objects.count(), 1)
        self.assertEqual(ReviewImageSnapshot.objects.count(), 1)

    def test_accepted_submission_replay_after_archive_still_returns_saved_snapshot(self):
        token = self.token()
        record, _ = self.submit(token=token)
        services.archive_question(self.user, self.question.pk, True)
        repeated, created = self.submit(token=token)
        self.assertFalse(created)
        self.assertEqual(repeated.pk, record.pk)
        self.assertEqual(SchedulingState.objects.get().revision, 1)

    def test_two_signed_pages_with_frozen_updated_at_still_advance_once(self):
        first, stale = self.token(), self.token()
        before = services.review_version(self.question)
        record, _ = self.submit(token=first)
        self.question.refresh_from_db()
        self.assertEqual(self.question.updated_at, NOW)
        self.assertNotEqual(services.review_version(self.question), before)
        with self.assertRaises(ValidationError):
            self.submit(token=stale)
        self.assertEqual(ReviewRecord.objects.count(), 1)
        self.assertEqual(SchedulingState.objects.get().revision, 1)
        self.assertEqual(ScheduleEvent.objects.count(), 1)

    def test_scheduler_revision_alone_invalidates_signed_page(self):
        self.submit()
        WrongQuestion.objects.filter(pk=self.question.pk).update(next_review_date=TODAY)
        token = self.token()
        version = services.review_version(self.question)
        SchedulingState.objects.filter(question=self.question).update(revision=F('revision') + 1)
        self.assertNotEqual(services.review_version(self.question), version)
        with patch('learning.services.prepare_schedule', wraps=services.prepare_schedule) as prepare:
            with self.assertRaises(ValidationError):
                self.submit(token=token)
            prepare.assert_not_called()
        self.assertEqual(SchedulingState.objects.get().revision, 2)
        self.assertEqual(ReviewRecord.objects.count(), 1)

    def test_image_relation_change_invalidates_signed_page_without_timestamp_change(self):
        token = self.token()
        self.question.image_links.all().delete()
        with self.assertRaises(ValidationError):
            self.submit(token=token)
        self.assert_no_partial_review()

    def test_manual_override_records_suggestion_and_actual_date(self):
        chosen = TODAY + timedelta(days=15)
        record, _ = self.submit('good', next_review_date=chosen)
        event = record.schedule_event
        self.assertEqual(event.manual_override_date, chosen)
        self.assertEqual(event.suggested_date, TODAY + timedelta(days=2))
        self.assertEqual(event.applied_date, chosen)
        self.assertEqual(record.next_review_date, chosen)
        self.assertEqual(event.due_utc, NOW + timedelta(days=2))

    @override_settings(TIME_ZONE='UTC')
    def test_root_service_uses_shanghai_date_even_if_active_timezone_is_utc(self):
        stamp = datetime(2026, 10, 3, 16, 0, tzinfo=dt_timezone.utc)
        with patch('learning.services.timezone.now', return_value=stamp):
            record, _ = self.submit('again')
        self.assertEqual(record.review_date.isoformat(), '2026-10-04')
        self.assertEqual(record.next_review_date.isoformat(), '2026-10-05')
        self.assertEqual(record.schedule_event.reviewed_at, stamp)
        self.assertEqual(record.schedule_event.due_utc, stamp + timedelta(days=1))

    def test_failing_after_image_snapshot_rolls_back_all_new_records(self):
        real_snapshot = services.snapshot_question_images
        def snapshot_then_fail(question, record):
            real_snapshot(question, record)
            raise RuntimeError('synthetic failure after image snapshot')
        with patch('learning.services.snapshot_question_images', side_effect=snapshot_then_fail):
            with self.assertRaises(RuntimeError):
                self.submit()
        self.assert_no_partial_review()

    def test_failing_schedule_event_insert_rolls_back_images_and_history(self):
        with patch.object(ScheduleEvent, 'save', side_effect=RuntimeError('synthetic event failure')):
            with self.assertRaises(RuntimeError):
                self.submit()
        self.assert_no_partial_review()

    def test_failing_state_advance_after_event_rolls_back_everything(self):
        real_save = SchedulingState.save
        def fail_advance(state, *args, **kwargs):
            if state.revision == 1:
                raise RuntimeError('synthetic state advance failure')
            return real_save(state, *args, **kwargs)
        with patch.object(SchedulingState, 'save', autospec=True, side_effect=fail_advance):
            with self.assertRaises(RuntimeError):
                self.submit()
        self.assert_no_partial_review()

    def test_failing_final_question_due_update_rolls_back_everything(self):
        real_save = WrongQuestion.save
        def fail_due_update(question, *args, **kwargs):
            if question.pk == self.question.pk and 'next_review_date' in kwargs.get('update_fields', ()):
                raise RuntimeError('synthetic final due failure')
            return real_save(question, *args, **kwargs)
        with patch.object(WrongQuestion, 'save', autospec=True, side_effect=fail_due_update):
            with self.assertRaises(RuntimeError):
                self.submit()
        self.assert_no_partial_review()

    def test_corrupt_existing_state_is_preserved_and_never_uses_legacy_fallback(self):
        self.submit()
        WrongQuestion.objects.filter(pk=self.question.pk).update(next_review_date=TODAY)
        SchedulingState.objects.filter(question=self.question).update(card_state={'corrupt': 'synthetic'})
        with self.assertRaises(ScheduleStateError):
            self.submit()
        self.assertEqual(SchedulingState.objects.get().card_state, {'corrupt': 'synthetic'})
        self.assertEqual(SchedulingState.objects.get().revision, 1)
        self.assertEqual(ReviewRecord.objects.count(), 1)
        self.assertEqual(ScheduleEvent.objects.count(), 1)
        self.assertEqual(ReviewImageManifest.objects.count(), 1)
        self.assertEqual(ReviewImageSnapshot.objects.count(), 1)

    def test_foreign_owner_and_archived_question_create_no_schedule_or_snapshots(self):
        other_token = services.reveal_token(services.make_token(self.other, 'review', self.question),
                                           self.other, self.question)
        with self.assertRaises(Http404):
            services.submit_review(self.other, self.question.pk, {'answer': 'synthetic', 'rating': 'hard'}, other_token)
        token = self.token()
        services.archive_question(self.user, self.question.pk, True)
        with self.assertRaises(ValidationError):
            self.submit(token=token)
        self.assert_no_partial_review()

    def test_legacy_record_retains_its_old_three_day_semantics(self):
        old_time = NOW - timedelta(days=20)
        old_date = old_time.astimezone(SHANGHAI).date()
        legacy = ReviewRecord.objects.create(
            question=self.question, reviewed_at=old_time, review_date=old_date,
            answer='Legacy synthetic answer', rating='hard', note='Legacy synthetic note',
            next_review_date=old_date + timedelta(days=3), title_snapshot='Legacy title',
            question_snapshot='Legacy question', original_answer_snapshot='Legacy original',
            correct_answer_snapshot='Legacy correct', error_reason_snapshot='Legacy reason',
            course_snapshot=self.course.name, knowledge_points_snapshot=[], submission_key=uuid.uuid4())
        self.submit('good')
        legacy.refresh_from_db()
        self.assertEqual(legacy.next_review_date, old_date + timedelta(days=3))
        self.assertEqual(legacy.rating, 'hard')
        self.assertFalse(ScheduleEvent.objects.filter(review_record=legacy).exists())
        self.assertFalse(ReviewImageManifest.objects.filter(review=legacy).exists())
        self.assertIsNone(ScheduleEvent.objects.get().before_state['last_review'])

    def test_http_reveal_previews_do_not_write_until_explicit_save(self):
        self.client.force_login(self.user)
        url = f'/reviews/{self.question.pk}/'
        initial = self.client.get(url)
        revealed = self.client.post(url, {'action': 'reveal', 'answer': 'Synthetic answer',
                                          'token': initial.context['form'].initial['token']})
        self.assertEqual(revealed.status_code, 200)
        self.assertEqual(set(revealed.context['schedule_suggestions']), {'again', 'hard', 'good'})
        self.assert_no_partial_review()
        response = self.client.post(url, {'action': 'save', 'answer': 'Synthetic answer', 'rating': 'good',
                                         'token': revealed.context['form'].initial['token'],
                                         'next_review_date': ''})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ScheduleEvent.objects.count(), 1)
        self.assertEqual(ReviewImageManifest.objects.get().image_count, 1)

    def test_malformed_manual_date_is_validation_error_and_rolls_back(self):
        token = self.token()
        for bad_date in ('2026-10-07', NOW, 7):
            with self.subTest(value=bad_date), self.assertRaises(ValidationError):
                self.submit(token=token, next_review_date=bad_date)
        self.assert_no_partial_review()

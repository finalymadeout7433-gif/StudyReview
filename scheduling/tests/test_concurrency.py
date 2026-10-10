from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, override_settings

from learning.models import Course, ReviewRecord, WrongQuestion
from scheduling.models import ScheduleEvent, SchedulingState
from scheduling import services
from scheduling.engine import SHANGHAI
from .test_workflow import NOW, save_review


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SchedulingMySQLConcurrencyTests(TransactionTestCase):
    def _fixture_teardown(self):
        if connection.vendor == 'mysql':
            name = connection.settings_dict['NAME']
            authorized = getattr(settings, 'AUTHORIZED_MIGRATION_SCHEMAS', ())
            if name not in authorized or not name.startswith('test_study_review_v2_'):
                raise RuntimeError('Refusing immutable-history cleanup outside explicit V2 test schemas.')
            with connection.cursor() as cursor:
                cursor.execute('SET FOREIGN_KEY_CHECKS=0')
                try:
                    cursor.execute('TRUNCATE TABLE scheduling_scheduleevent')
                    cursor.execute('TRUNCATE TABLE learning_reviewrecord')
                finally:
                    cursor.execute('SET FOREIGN_KEY_CHECKS=1')
        super()._fixture_teardown()

    def setUp(self):
        if connection.vendor != 'mysql':
            self.skipTest('FSRS concurrency acceptance requires MySQL row locks.')
        self.user = User.objects.create_user('fsrs_concurrency_owner')
        self.course = Course.objects.create(owner=self.user, name='Synthetic concurrency')
        self.question = WrongQuestion.objects.create(
            course=self.course, title='Synthetic concurrency question', content='Synthetic only',
            original_answer='old', correct_answer='correct', error_reason='test',
            next_review_date=NOW.astimezone(SHANGHAI).date())

    def race(self, keys):
        barrier = Barrier(len(keys))
        def worker(key):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=10)
                with transaction.atomic():
                    Course.objects.select_for_update().get(pk=self.course.pk, owner=user)
                    question = WrongQuestion.objects.select_for_update().select_related('course').get(
                        pk=self.question.pk, course__owner=user)
                    existing = ReviewRecord.objects.filter(submission_key=key).first()
                    if existing is not None:
                        return ('ok', existing.pk, False)
                    # Equivalent to caller's signed page schedule revision (initial zero).
                    if services.schedule_revision(user, question) != 0:
                        return ('stale', None, False)
                    proposal = services.prepare_schedule(user, question, 'hard', NOW)
                    record = save_review(question, proposal, submission_key=key)
                    services.commit_schedule(proposal, record)
                    question.next_review_date = record.next_review_date
                    question.save(update_fields=['next_review_date', 'updated_at'])
                    return ('ok', record.pk, True)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            return list(pool.map(worker, keys))

    def test_first_state_parallel_replay_creates_one_state_review_and_event(self):
        key = uuid.uuid4()
        result = self.race([key] * 4)
        self.assertEqual([row[0] for row in result], ['ok'] * 4)
        self.assertEqual(sum(row[2] for row in result), 1)
        self.assertEqual(len({row[1] for row in result}), 1)
        self.assertEqual(SchedulingState.objects.count(), 1)
        self.assertEqual(ReviewRecord.objects.count(), 1)
        self.assertEqual(ScheduleEvent.objects.count(), 1)
        self.assertEqual(SchedulingState.objects.get().revision, 1)

    def test_two_page_revisions_advance_once(self):
        result = self.race([uuid.uuid4(), uuid.uuid4()])
        self.assertEqual(sorted(row[0] for row in result), ['ok', 'stale'])
        self.assertEqual(SchedulingState.objects.get().revision, 1)
        self.assertEqual(ScheduleEvent.objects.count(), 1)


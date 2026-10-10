from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from learning import services
from learning.models import Course, WrongQuestion, ReviewRecord
from scheduling.models import SchedulingState, ScheduleEvent


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class MySQLConcurrencyTests(TransactionTestCase):
    def _fixture_teardown(self):
        # Django's MySQL flush uses DELETE, intentionally blocked by history guards.
        # Only the disposable test schema may truncate synthetic history for cleanup.
        if connection.vendor == 'mysql':
            name = connection.settings_dict['NAME']
            expected = connection.settings_dict.get('TEST', {}).get('NAME')
            authorized = getattr(settings, 'AUTHORIZED_MIGRATION_SCHEMAS', ())
            if name != expected or name not in authorized or not name.startswith('test_'):
                raise RuntimeError('Refusing cleanup outside the dedicated test schema.')
            immutable_tables = [
                'scheduling_scheduleevent', 'attachments_reviewimagesnapshot',
                'attachments_reviewimagemanifest', 'attachments_attachment',
                'learning_reviewrecord',
            ]
            existing = set(connection.introspection.table_names())
            with connection.cursor() as cursor:
                cursor.execute('SET FOREIGN_KEY_CHECKS=0')
                try:
                    for table in immutable_tables:
                        if table in existing:
                            cursor.execute(f'TRUNCATE TABLE {connection.ops.quote_name(table)}')
                finally:
                    cursor.execute('SET FOREIGN_KEY_CHECKS=1')
        super()._fixture_teardown()

    def setUp(self):
        if connection.vendor != 'mysql':
            self.skipTest('Concurrency acceptance requires MySQL row locks; SQLite is not a substitute.')
        self.clock = patch('learning.services.timezone.now',
                           return_value=datetime(2026, 10, 3, 12, tzinfo=dt_timezone.utc))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.user = User.objects.create_user('并发测试学生', password='concurrency-study!')
        self.course = Course.objects.create(owner=self.user, name='并发验证课程')
        self.question = WrongQuestion.objects.create(course=self.course, title='并发复习题', content='事务应怎样提交？',
            original_answer='分步提交', correct_answer='一起提交或一起回滚', error_reason='缺少原子性', next_review_date=timezone.localdate())

    def token(self):
        return services.reveal_token(services.make_token(self.user, 'review', self.question), self.user, self.question)

    def race(self, tokens):
        barrier = Barrier(len(tokens))
        def worker(token):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=10)
                try:
                    record, created = services.submit_review(user, self.question.pk, {'answer': '一起保存', 'rating': 'hard'}, token)
                    return ('ok', record.pk, created)
                except ValidationError:
                    return ('stale', None, False)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(tokens)) as pool:
            return list(pool.map(worker, tokens))

    def test_same_submission_parallel_replay_creates_exactly_one_record(self):
        token = self.token()
        results = self.race([token, token, token, token])
        self.assertEqual([row[0] for row in results], ['ok'] * 4)
        self.assertEqual(len({row[1] for row in results}), 1)
        self.assertEqual(sum(row[2] for row in results), 1)
        self.assertEqual(ReviewRecord.objects.count(), 1)
        self.question.refresh_from_db()
        self.assertEqual(self.question.next_review_date, timezone.localdate() + timedelta(days=1))
        self.assertEqual(SchedulingState.objects.get().revision, 1)
        self.assertEqual(ScheduleEvent.objects.count(), 1)

    def test_two_tabs_different_keys_same_version_only_one_advances(self):
        results = self.race([self.token(), self.token()])
        self.assertEqual(sorted(row[0] for row in results), ['ok', 'stale'])
        self.assertEqual(ReviewRecord.objects.count(), 1)

    def test_archive_commit_before_review_rejects_review(self):
        token = self.token()
        services.archive_course(self.user, self.course.pk, True)
        results = self.race([token, token])
        self.assertEqual([row[0] for row in results], ['stale', 'stale'])
        self.assertEqual(ReviewRecord.objects.count(), 0)
        self.question.refresh_from_db()
        self.assertEqual(self.question.next_review_date, timezone.localdate())

    def test_archive_and_review_race_has_consistent_final_state(self):
        barrier = Barrier(2)
        token = self.token()
        def worker(operation):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=10)
                if operation == 'archive':
                    services.archive_course(user, self.course.pk, True)
                    return 'archived'
                try:
                    services.submit_review(user, self.question.pk, {'answer': '事务一起提交', 'rating': 'good'}, token)
                    return 'reviewed'
                except ValidationError:
                    return 'blocked'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, ['archive', 'review']))
        self.course.refresh_from_db()
        self.question.refresh_from_db()
        self.assertTrue(self.course.is_archived)
        count = ReviewRecord.objects.count()
        self.assertEqual(count, 1 if 'reviewed' in results else 0)
        self.assertEqual(self.question.next_review_date, timezone.localdate() + timedelta(days=2) if count else timezone.localdate())
        self.assertEqual(ScheduleEvent.objects.count(), count)

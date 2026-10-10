"""Real MySQL locks, exclusively in the root-authorized synthetic chat test DB."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, close_old_connections, connections
from django.test import TransactionTestCase
from django.utils import timezone
from learning.models import Course, WrongQuestion, Task
from learning import services as learning_services
from assistant import services
from assistant.models import Draft, Message


class AssistantMySQLConcurrencyTests(TransactionTestCase):
    def task_draft(self):
        task=Task.objects.create(course=self.course,title='合成状态任务',description='原笔记',due_date=timezone.localdate())
        preview=services.target_preview(self.user,'task',task.pk)
        draft,_=services.create_draft(self.user,self.session.pk,{'operation':'update_task','target_id':task.pk,
            'expected_version':preview['expected_version'],'payload':{'status':'done','description':'确认后的笔记'},
            'submission_key':str(uuid.uuid4())})
        return task,draft

    def test_rc7_parallel_task_confirmations_apply_once(self):
        task,draft=self.task_draft();token=services.confirmation_token(draft)
        result=self.race([uuid.uuid4(),uuid.uuid4()],lambda user,key:services.confirm_draft(user,draft.pk,token,key)[1])
        self.assertEqual(sorted(result),[False,True])
        task.refresh_from_db();self.assertEqual(task.status,'done');self.assertIsNotNone(task.completed_at)
        self.assertEqual(task.description,'确认后的笔记')
        draft.refresh_from_db();self.assertEqual(draft.status,'applied')

    def test_rc7_cancel_and_confirm_have_one_consistent_winner(self):
        task,draft=self.task_draft();token=services.confirmation_token(draft)
        def action(user,kind):
            try:
                if kind=='cancel':services.cancel_draft(user,draft.pk)
                else:services.confirm_draft(user,draft.pk,token,uuid.uuid4())
                return kind,True
            except services.Conflict:
                return kind,False
        result=self.race(['cancel','confirm'],action)
        self.assertEqual(sum(ok for kind,ok in result),1)
        task.refresh_from_db();draft.refresh_from_db()
        if draft.status=='applied':
            self.assertEqual(task.status,'done');self.assertGreater(draft.expires_at,draft.created_at)
        else:
            self.assertEqual(task.status,'todo');self.assertEqual(task.description,'原笔记')
            self.assertEqual(draft.expires_at,draft.created_at)

    def _fixture_teardown(self):
        if connection.vendor == 'mysql':
            name = connection.settings_dict['NAME']
            expected = settings.DATABASES['default']['TEST']['NAME']
            if (settings.SETTINGS_MODULE not in {'config.v2_chat_test_settings', 'config.v2_integrated_test_settings'} or name != expected
                    or not name.startswith('test_study_review_v2_')
                    or name not in settings.AUTHORIZED_MIGRATION_SCHEMAS):
                raise RuntimeError('Refusing synthetic cleanup outside the exact dedicated chat test schema.')
            # Only synthetic immutable tables of this precise schema. Keep all DBs.
            # MySQL DELETE flush would intentionally trip immutable history guards.
            with connection.cursor() as cursor:
                cursor.execute('SET FOREIGN_KEY_CHECKS=0')
                try:
                    for table in ('attachments_reviewimagesnapshot', 'attachments_reviewimagemanifest',
                            'learning_reviewrecord', 'attachments_attachment'):
                        cursor.execute(f'TRUNCATE TABLE `{table}`')
                finally:
                    cursor.execute('SET FOREIGN_KEY_CHECKS=1')
        super()._fixture_teardown()

    def setUp(self):
        if connection.vendor != 'mysql':
            self.skipTest('MySQL row-lock acceptance cannot be replaced by SQLite.')
        self.user = get_user_model().objects.create_user('synthetic_chat_parallel')
        self.course = Course.objects.create(owner=self.user, name='合成并发课程')
        self.question = WrongQuestion.objects.create(course=self.course, title='旧合成题', content='合成题干',
            original_answer='原作答', correct_answer='参考答案', error_reason='错因', next_review_date=timezone.localdate())
        self.session, _ = services.create_session(self.user, '合成并发会话', uuid.uuid4())

    def race(self, tasks, action):
        barrier = Barrier(len(tasks))
        def worker(value):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.user.pk)
                barrier.wait(timeout=10)
                return action(user, value)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            return list(pool.map(worker, tasks))

    def proposal(self):
        return {'operation': 'create_question', 'submission_key': str(uuid.uuid4()),
            'payload': {'course_id': self.course.pk, 'title': '新合成题', 'content': '新合成题干',
                'original_answer': '原作答', 'correct_answer': '参考答案', 'error_reason': '错因',
                'next_review_date': (timezone.localdate() + timedelta(days=1)).isoformat()}}

    def test_four_session_creation_replays_one_session(self):
        key = uuid.uuid4()
        def action(user, value):
            session, created = services.create_session(user, '同一并发会话', value)
            return str(session.pk), created
        results = self.race([key] * 4, action)
        self.assertEqual(len({item[0] for item in results}), 1)
        self.assertEqual(sum(item[1] for item in results), 1)

    def test_four_message_replays_one_user_and_one_system_notice(self):
        key = uuid.uuid4()
        def action(user, value):
            message, notice, created = services.append_message(user, self.session.pk, '并发合成消息', [], value)
            return str(message.pk), str(notice.pk), created
        results = self.race([key] * 4, action)
        self.assertEqual(len({item[0] for item in results}), 1)
        self.assertEqual(len({item[1] for item in results}), 1)
        self.assertEqual(sum(item[2] for item in results), 1)
        self.assertEqual(Message.objects.count(), 2)

    def test_four_draft_creation_replays_one_preview(self):
        proposal = self.proposal()
        def action(user, value):
            draft, created = services.create_draft(user, self.session.pk, value)
            return str(draft.pk), created
        results = self.race([proposal] * 4, action)
        self.assertEqual(len({item[0] for item in results}), 1)
        self.assertEqual(sum(item[1] for item in results), 1)
        self.assertEqual(Draft.objects.count(), 1)
        self.assertEqual(WrongQuestion.objects.count(), 1)

    def test_four_confirm_replays_one_question_and_one_applied_draft(self):
        draft, _ = services.create_draft(self.user, self.session.pk, self.proposal())
        token = services.confirmation_token(draft)
        def action(user, value):
            saved, applied = services.confirm_draft(user, draft.pk, token, value)
            return saved.applied_object_id, applied
        results = self.race([uuid.uuid4()] * 4, action)
        self.assertEqual(len({item[0] for item in results}), 1)
        self.assertEqual(sum(item[1] for item in results), 1)
        self.assertEqual(WrongQuestion.objects.count(), 2)

    def test_two_drafts_same_question_version_only_one_applies(self):
        version = services.target_preview(self.user, 'question', self.question.pk)['expected_version']
        drafts = []
        for title in ('第一份合成修改', '第二份合成修改'):
            draft, _ = services.create_draft(self.user, self.session.pk, {'operation': 'update_question',
                'target_id': self.question.pk, 'expected_version': version,
                'payload': {'title': title}, 'submission_key': str(uuid.uuid4())})
            drafts.append((draft.pk, services.confirmation_token(draft)))
        def action(user, value):
            try:
                services.confirm_draft(user, value[0], value[1], uuid.uuid4())
                return 'applied'
            except services.Conflict:
                return 'stale'
        self.assertEqual(sorted(self.race(drafts, action)), ['applied', 'stale'])
        self.assertEqual(Draft.objects.filter(status='applied').count(), 1)

    def test_archive_and_confirmation_race_stays_consistent(self):
        draft, _ = services.create_draft(self.user, self.session.pk, self.proposal())
        token = services.confirmation_token(draft)
        def action(user, value):
            if value == 'archive':
                learning_services.archive_course(user, self.course.pk, True)
                return 'archived'
            try:
                services.confirm_draft(user, draft.pk, token, uuid.uuid4())
                return 'applied'
            except ValidationError:
                return 'blocked'
        results = self.race(['archive', 'confirm'], action)
        self.course.refresh_from_db()
        draft.refresh_from_db()
        self.assertTrue(self.course.is_archived)
        applied = 'applied' in results
        self.assertEqual(draft.status, 'applied' if applied else 'pending')
        self.assertEqual(WrongQuestion.objects.count(), 2 if applied else 1)

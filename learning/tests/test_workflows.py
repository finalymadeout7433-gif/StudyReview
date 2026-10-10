import uuid
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, DatabaseError, connection, transaction
from django.http import Http404
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from learning import services
from learning.forms import QuestionForm, ReviewForm
from learning.models import Course, KnowledgePoint, Task, WrongQuestion, ReviewRecord, QuestionKnowledgePoint


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user('学生甲', password='Study-Demo-2026!')
        cls.b = User.objects.create_user('学生乙', password='Other-Demo-2026!')
        cls.course = Course.objects.create(owner=cls.a, name='数据库系统原理', description='关系数据库')
        cls.other_course = Course.objects.create(owner=cls.a, name='高等数学')
        cls.b_course = Course.objects.create(owner=cls.b, name='乙的私有课程')
        cls.point = KnowledgePoint.objects.create(course=cls.course, name='主键与外键')
        cls.other_point = KnowledgePoint.objects.create(course=cls.other_course, name='导数')
        cls.b_point = KnowledgePoint.objects.create(course=cls.b_course, name='乙的知识点')
        cls.question = WrongQuestion.objects.create(course=cls.course, title='主键和外键的作用', content='两种键分别是什么？',
            original_answer='外键必须唯一', correct_answer='参考答案秘密标记：主键标识行，外键维护引用完整性',
            error_reason='混淆唯一性与引用约束', next_review_date=timezone.localdate())
        QuestionKnowledgePoint.objects.create(question=cls.question, knowledge_point=cls.point)
        cls.b_question = WrongQuestion.objects.create(course=cls.b_course, title='乙的私有题目', content='不应泄露',
            original_answer='未作答', correct_answer='不应泄露答案', error_reason='不应泄露原因', next_review_date=timezone.localdate())
        cls.task = Task.objects.create(course=cls.course, title='完成数据库约束练习', due_date=timezone.localdate())
        cls.b_task = Task.objects.create(course=cls.b_course, title='乙的私有任务', due_date=timezone.localdate())

    def setUp(self):
        self.client.force_login(self.a)

    def review_token(self, question=None):
        question = question or self.question
        question.refresh_from_db()
        return services.reveal_token(services.make_token(self.a, 'review', question), self.a, question)

    def review_values(self, **kwargs):
        return {'answer': '主键唯一标识一行，外键引用已有键', 'rating': 'hard', 'note': '重新理清约束', **kwargs}

    def question_values(self, **kwargs):
        return {'course': self.course, 'title': '另一道题', 'content': '请描述完整性约束', 'original_answer': '未作答',
            'correct_answer': '实体、参照与用户定义完整性', 'error_reason': '遗漏参照完整性',
            'next_review_date': timezone.localdate(), 'knowledge_points': [self.point], **kwargs}

    def test_anonymous_pages_require_login(self):
        self.client.logout()
        for name in ('dashboard', 'course-list', 'task-list', 'question-list', 'review-queue', 'statistics'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.url)

    def test_all_primary_pages_render(self):
        for url in ['/', '/courses/', f'/courses/{self.course.pk}/', '/courses/new/', '/tasks/',
            '/tasks/new/', f'/tasks/{self.task.pk}/edit/', '/questions/', '/questions/new/',
            f'/questions/{self.question.pk}/', f'/questions/{self.question.pk}/edit/', '/reviews/',
            f'/reviews/{self.question.pk}/', '/statistics/']:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, '乙的私有')

    def test_continuous_acceptance_via_http_forms(self):
        self.client.logout()
        self.client.post('/accounts/register/', {'username': '流程验收同学', 'password1': 'Flow-test-2026!', 'password2': 'Flow-test-2026!'})
        user = User.objects.get(username='流程验收同学')
        response = self.client.post('/courses/new/', {'name': '软件验收课程', 'description': '中文数据自产验证'})
        self.assertEqual(response.status_code, 302)
        course = Course.objects.get(owner=user, name='软件验收课程')
        self.assertEqual(self.client.post(f'/courses/{course.pk}/points/new/', {'name': '事务原子性'}).status_code, 302)
        point = course.knowledge_points.get()
        task_token = self.client.get('/tasks/new/').context['form'].initial['token']
        task_data = {'course': course.pk, 'title': '完成约束练习', 'due_date': timezone.localdate(), 'description': '', 'token': task_token}
        self.assertEqual(self.client.post('/tasks/new/', task_data).status_code, 302)
        self.assertEqual(self.client.post('/tasks/new/', task_data).status_code, 302)
        task = course.tasks.get()
        question_token = self.client.get('/questions/new/').context['form'].initial['token']
        data = {'course': course.pk, 'title': '原子性是什么', 'content': '两项写入怎样保持一致？', 'original_answer': '分别保存',
            'correct_answer': '一起成功或一起回滚', 'error_reason': '遗漏异常失败场景', 'knowledge_points': [point.pk],
            'next_review_date': timezone.localdate(), 'token': question_token}
        self.assertEqual(self.client.post('/questions/new/', data).status_code, 302)
        self.assertEqual(self.client.post('/questions/new/', data).status_code, 302)
        question = course.questions.get()
        url = f'/reviews/{question.pk}/'
        token = self.client.get(url).context['form'].initial['token']
        response = self.client.post(url, {'action': 'reveal', 'answer': '应一起保存', 'token': token})
        token = response.context['form'].initial['token']
        self.assertEqual(self.client.post(url, {'action': 'save', 'answer': '应一起保存', 'rating': 'hard', 'token': token}).status_code, 302)
        self.assertEqual(question.reviews.count(), 1)
        self.assertEqual(self.client.post(f'/tasks/{task.pk}/status/', {'action': 'done'}).status_code, 302)
        self.assertEqual(self.client.get('/statistics/').context['stats']['completion_rate'], 100.0)
        self.assertEqual(self.client.post(f'/courses/{course.pk}/archive/', {'action': 'archive'}).status_code, 302)
        self.assertEqual(self.client.post(f'/tasks/{task.pk}/status/', {'action': 'todo'}).status_code, 403)
        self.assertContains(self.client.get(f'/questions/{question.pk}/'), '应一起保存')
        self.assertEqual(self.client.post(f'/courses/{course.pk}/archive/', {'action': 'restore'}).status_code, 302)
        question.refresh_from_db()
        self.assertEqual(question.next_review_date, question.reviews.get().review_date + timedelta(days=1))

    def test_question_form_edit_updates_links_but_not_history(self):
        record, _ = services.submit_review(self.a, self.question.pk, self.review_values(), self.review_token())
        self.question.refresh_from_db()
        values = self.question_values(title='通过表单编辑', correct_answer='新的参考答案', knowledge_points=[])
        response = self.client.post(f'/questions/{self.question.pk}/edit/', {**values, 'course': self.other_course.pk})
        self.assertEqual(response.status_code, 302)
        self.question.refresh_from_db()
        self.assertEqual(self.question.course_id, self.course.pk)
        self.assertEqual(self.question.knowledge_points.count(), 0)
        self.assertEqual(self.question.title, '通过表单编辑')
        record.refresh_from_db()
        self.assertNotEqual(record.correct_answer_snapshot, self.question.correct_answer)

    def test_registration_login_and_post_logout(self):
        self.client.logout()
        response = self.client.post('/accounts/register/', {'username': '新同学', 'password1': 'A-long-study-2026!', 'password2': 'A-long-study-2026!'})
        self.assertRedirects(response, '/courses/new/')
        user = User.objects.get(username='新同学')
        self.assertTrue(user.check_password('A-long-study-2026!'))
        self.assertNotEqual(user.password, 'A-long-study-2026!')
        self.assertEqual(self.client.get('/accounts/logout/').status_code, 405)
        self.assertRedirects(self.client.post('/accounts/logout/'), '/accounts/login/')
        self.assertRedirects(self.client.post('/accounts/login/', {'username': '新同学', 'password': 'A-long-study-2026!'}), '/')

    def test_invalid_login_and_registration_retain_errors(self):
        self.client.logout()
        self.assertEqual(self.client.post('/accounts/login/', {'username': '学生甲', 'password': 'wrong'}).status_code, 200)
        self.assertEqual(self.client.post('/accounts/register/', {'username': '新同学', 'password1': '123', 'password2': '456'}).status_code, 200)
        self.assertFalse(User.objects.filter(username='新同学').exists())

    def test_course_name_unique_including_archive(self):
        services.archive_course(self.a, self.course.pk, True)
        response = self.client.post('/courses/new/', {'name': self.course.name, 'description': '不能重名'})
        self.assertContains(response, '已有同名课程')
        self.assertEqual(Course.objects.filter(owner=self.a, name=self.course.name).count(), 1)
        # Another owner can use the same name.
        services.save_course(self.b, {'name': self.course.name})

    def test_database_unique_course_point_and_link(self):
        for model, values in [
            (Course, {'owner': self.a, 'name': self.course.name}),
            (KnowledgePoint, {'course': self.course, 'name': self.point.name}),
        ]:
            with self.subTest(model=model.__name__), self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.create(**values)
        with self.assertRaises(ValidationError):
            QuestionKnowledgePoint.objects.create(question=self.question, knowledge_point=self.point)

    def test_owner_isolation_lists_search_filters_and_points(self):
        for url in ['/', '/courses/?archive=all', '/tasks/?archive=all', '/questions/?archive=all',
            '/reviews/', '/statistics/']:
            self.assertNotContains(self.client.get(url), '乙的私有')
        search_response = self.client.get('/questions/?q=乙的私有')
        self.assertEqual(search_response.context['page_obj'].paginator.count, 0)
        self.assertNotContains(search_response, '乙的私有题目')
        for url in [f'/tasks/?course={self.b_course.pk}', f'/questions/?course={self.b_course.pk}',
            f'/questions/?point={self.b_point.pk}', f'/courses/{self.b_course.pk}/points.json']:
            self.assertEqual(self.client.get(url).status_code, 404)
        response = self.client.get('/statistics/', {'course': self.b_course.pk, 'start': timezone.localdate(), 'end': timezone.localdate()})
        self.assertContains(response, '选择一个有效的选项')

    def test_owner_isolation_all_object_urls_and_writes(self):
        for url in [f'/courses/{self.b_course.pk}/', f'/courses/{self.b_course.pk}/edit/',
            f'/courses/{self.b_course.pk}/points/new/', f'/courses/{self.b_course.pk}/points/{self.b_point.pk}/edit/',
            f'/courses/{self.b_course.pk}/points/{self.b_point.pk}/delete/', f'/tasks/{self.b_task.pk}/edit/',
            f'/tasks/{self.b_task.pk}/delete/', f'/questions/{self.b_question.pk}/',
            f'/questions/{self.b_question.pk}/edit/', f'/reviews/{self.b_question.pk}/']:
            for method in ('get', 'post'):
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method)(url, {'action': 'reveal', 'answer': '未作答', 'token': 'invalid'})
                    self.assertEqual(response.status_code, 404)
                    self.assertNotContains(response, '不应泄露', status_code=404)
        for url, data in [(f'/courses/{self.b_course.pk}/archive/', {'action': 'archive'}),
            (f'/tasks/{self.b_task.pk}/status/', {'action': 'done'}),
            (f'/questions/{self.b_question.pk}/archive/', {'action': 'archive'})]:
            self.assertEqual(self.client.post(url, data).status_code, 404)

    def test_foreign_course_creation_rejected(self):
        response = self.client.post('/tasks/new/', {'title': '非法任务', 'course': self.b_course.pk,
            'due_date': timezone.localdate(), 'token': services.make_token(self.a, 'task-create')})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Task.objects.filter(title='非法任务').exists())
        with self.assertRaises(Http404):
            services.save_question(self.a, self.question_values(course=self.b_course), token=services.make_token(self.a, 'question-create'))

    def test_same_course_points_validated_in_forms_and_module(self):
        values = self.question_values()
        form = QuestionForm({**values, 'course': self.course.pk, 'knowledge_points': [self.other_point.pk]}, user=self.a)
        self.assertFalse(form.is_valid())
        self.assertIn('knowledge_points', form.errors)
        for point in [self.other_point, self.b_point]:
            with self.assertRaises(ValidationError):
                services.save_question(self.a, self.question_values(knowledge_points=[point]), token=services.make_token(self.a, 'question-create'))
            with self.assertRaises(ValidationError):
                QuestionKnowledgePoint.objects.create(question=self.question, knowledge_point=point)

    def test_mysql_same_course_guard_catches_bulk_and_raw_writes(self):
        if connection.vendor != 'mysql':
            self.skipTest('Requires actual MySQL trigger')
        with self.assertRaises(DatabaseError), transaction.atomic():
            QuestionKnowledgePoint.objects.bulk_create([QuestionKnowledgePoint(question=self.question, knowledge_point=self.other_point)])

    def test_referenced_point_cannot_be_deleted_then_unlink_allows(self):
        with self.assertRaises(ValidationError):
            services.delete_point(self.a, self.course.pk, self.point.pk)
        response = self.client.post(f'/courses/{self.course.pk}/points/{self.point.pk}/delete/')
        self.assertContains(response, '已被错题引用')
        services.save_question(self.a, self.question_values(knowledge_points=[]), pk=self.question.pk)
        services.delete_point(self.a, self.course.pk, self.point.pk)
        self.assertFalse(KnowledgePoint.objects.filter(pk=self.point.pk).exists())

    def test_task_creation_replay_is_idempotent(self):
        token = services.make_token(self.a, 'task-create')
        values = {'course': self.course, 'title': '重复任务', 'description': '', 'due_date': timezone.localdate()}
        one = services.save_task(self.a, values, token=token)
        two = services.save_task(self.a, values, token=token)
        self.assertEqual(one.pk, two.pk)
        self.assertEqual(Task.objects.filter(title='重复任务').count(), 1)

    def test_question_creation_replay_is_idempotent(self):
        token = services.make_token(self.a, 'question-create')
        one = services.save_question(self.a, self.question_values(), token=token)
        two = services.save_question(self.a, self.question_values(), token=token)
        self.assertEqual(one.pk, two.pk)
        self.assertEqual(one.knowledge_points.count(), 1)

    def test_task_complete_restore_and_no_toggle_on_replay(self):
        services.set_task_status(self.a, self.task.pk, True)
        self.task.refresh_from_db()
        saved_time = self.task.completed_at
        self.assertIsNotNone(saved_time)
        services.set_task_status(self.a, self.task.pk, True)
        self.task.refresh_from_db()
        self.assertEqual(self.task.completed_at, saved_time)
        services.set_task_status(self.a, self.task.pk, False)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'todo')
        self.assertIsNone(self.task.completed_at)

    def test_task_completion_consistency_database_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Task.objects.filter(pk=self.task.pk).update(status='done', completed_at=None)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Task.objects.filter(pk=self.task.pk).update(status='todo', completed_at=timezone.now())

    def test_today_due_not_overdue_yesterday_due_is_overdue(self):
        self.assertFalse(self.task.is_overdue)
        Task.objects.filter(pk=self.task.pk).update(due_date=timezone.localdate() - timedelta(days=1))
        self.task.refresh_from_db()
        self.assertTrue(self.task.is_overdue)
        self.assertEqual(services.summary(self.a)['overdue'], 1)

    def test_task_delete_requires_post_confirmation(self):
        response = self.client.get(f'/tasks/{self.task.pk}/delete/')
        self.assertContains(response, '确认删除')
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())
        self.assertEqual(self.client.post(f'/tasks/{self.task.pk}/delete/').status_code, 302)
        self.assertFalse(Task.objects.filter(pk=self.task.pk).exists())

    def test_mutating_actions_reject_get_and_csrf_missing(self):
        for url in [f'/courses/{self.course.pk}/archive/', f'/tasks/{self.task.pk}/status/',
            f'/questions/{self.question.pk}/archive/']:
            self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.a)
        self.assertEqual(csrf_client.post(f'/tasks/{self.task.pk}/status/', {'action': 'done'}).status_code, 403)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'todo')

    def test_archive_course_readonly_and_restore_preserves_schedule(self):
        old_date = self.question.next_review_date
        token = self.review_token()
        services.archive_course(self.a, self.course.pk, True)
        self.assertEqual(services.summary(self.a)['due_count'], 0)
        for url in [f'/courses/{self.course.pk}/edit/', f'/tasks/{self.task.pk}/edit/',
            f'/questions/{self.question.pk}/edit/', f'/reviews/{self.question.pk}/']:
            self.assertEqual(self.client.get(url).status_code, 403)
        for call in [lambda: services.set_task_status(self.a, self.task.pk, True),
            lambda: services.save_point(self.a, self.course.pk, {'name': '新知识点'}),
            lambda: services.delete_point(self.a, self.course.pk, self.point.pk),
            lambda: services.save_task(self.a, {'course': self.course, 'title': '不允许', 'due_date': old_date}, token=services.make_token(self.a, 'task-create')),
            lambda: services.archive_question(self.a, self.question.pk, True),
            lambda: services.submit_review(self.a, self.question.pk, self.review_values(), token)]:
            with self.assertRaises(ValidationError):
                call()
        self.assertEqual(self.client.get(f'/questions/{self.question.pk}/').status_code, 200)
        services.archive_course(self.a, self.course.pk, False)
        self.question.refresh_from_db()
        self.assertEqual(self.question.next_review_date, old_date)
        self.assertEqual(services.summary(self.a)['due_count'], 1)

    def test_archive_question_readonly_and_restore(self):
        token = self.review_token()
        services.archive_question(self.a, self.question.pk, True)
        self.assertEqual(services.summary(self.a)['due_count'], 0)
        self.assertEqual(self.client.get(f'/questions/{self.question.pk}/edit/').status_code, 403)
        with self.assertRaises(ValidationError):
            services.submit_review(self.a, self.question.pk, self.review_values(), token)
        services.archive_question(self.a, self.question.pk, False)
        self.assertEqual(services.summary(self.a)['due_count'], 1)

    def test_reference_answer_absent_until_nonempty_answer_and_reveal(self):
        url = f'/reviews/{self.question.pk}/'
        response = self.client.get(url)
        self.assertNotContains(response, '参考答案秘密标记')
        token = response.context['form'].initial['token']
        invalid = self.client.post(url, {'action': 'reveal', 'answer': '   ', 'token': token})
        self.assertNotContains(invalid, '参考答案秘密标记')
        revealed = self.client.post(url, {'action': 'reveal', 'answer': '未作答', 'token': token})
        self.assertContains(revealed, '参考答案秘密标记')
        self.assertEqual(ReviewRecord.objects.count(), 0)
        bypass = self.client.post(url, {'action': 'save', 'answer': '未作答', 'rating': 'good', 'token': token})
        self.assertNotContains(bypass, '参考答案秘密标记')
        self.assertEqual(ReviewRecord.objects.count(), 0)

    def test_full_browserless_review_flow_and_replay(self):
        url = f'/reviews/{self.question.pk}/'
        initial = self.client.get(url)
        reveal = self.client.post(url, {'action': 'reveal', 'answer': '主键唯一，外键引用', 'token': initial.context['form'].initial['token']})
        token = reveal.context['form'].initial['token']
        data = {'action': 'save', 'answer': '主键唯一，外键引用', 'rating': 'hard', 'token': token, 'next_review_date': '', 'note': '记住了'}
        self.assertRedirects(self.client.post(url, data), '/reviews/')
        self.assertRedirects(self.client.post(url, data), '/reviews/')
        self.assertEqual(ReviewRecord.objects.filter(question=self.question).count(), 1)
        self.question.refresh_from_db()
        self.assertEqual(self.question.next_review_date, self.question.reviews.get().review_date + timedelta(days=1))
        self.assertEqual(services.summary(self.a)['review_total'], 1)

    def test_pinned_fsrs_cold_start_daily_recommendations(self):
        reviewed_at = datetime(2026, 10, 3, 12, tzinfo=dt_timezone.utc)
        with patch('learning.services.timezone.now', return_value=reviewed_at):
            for rating, days in [('again', 1), ('hard', 1), ('good', 2)]:
                with self.subTest(rating=rating):
                    question = services.save_question(self.a, self.question_values(title=rating), token=services.make_token(self.a, 'question-create'))
                    record, _ = services.submit_review(self.a, question.pk, self.review_values(rating=rating), self.review_token(question))
                    self.assertEqual(record.reviewed_at, reviewed_at)
                    self.assertEqual(record.next_review_date, date(2026, 10, 3) + timedelta(days=days))

    def test_custom_future_date_and_invalid_review_values(self):
        token = self.review_token()
        for values in [self.review_values(answer='  '), self.review_values(rating='invalid'),
            self.review_values(next_review_date=timezone.localdate()),
            self.review_values(next_review_date=timezone.localdate() - timedelta(days=1))]:
            with self.assertRaises(ValidationError):
                services.submit_review(self.a, self.question.pk, values, token)
        self.assertEqual(ReviewRecord.objects.count(), 0)
        record, _ = services.submit_review(self.a, self.question.pk,
            self.review_values(next_review_date=timezone.localdate() + timedelta(days=12)), token)
        self.assertEqual(record.next_review_date, timezone.localdate() + timedelta(days=12))

    def test_initial_date_validation_and_unchanged_overdue_edit(self):
        with self.assertRaises(ValidationError):
            services.save_question(self.a, self.question_values(next_review_date=timezone.localdate() - timedelta(days=1)), token=services.make_token(self.a, 'question-create'))
        past = timezone.localdate() - timedelta(days=5)
        WrongQuestion.objects.filter(pk=self.question.pk).update(next_review_date=past)
        services.save_question(self.a, self.question_values(next_review_date=past), pk=self.question.pk)
        self.question.refresh_from_db()
        self.assertEqual(self.question.next_review_date, past)

    def test_tampered_cross_user_cross_question_tokens_rejected(self):
        token = self.review_token()
        with self.assertRaises(ValidationError):
            services.submit_review(self.a, self.question.pk, self.review_values(), token + 'x')
        with self.assertRaises(ValidationError):
            services.submit_review(self.b, self.question.pk, self.review_values(), token)
        with self.assertRaises(ValidationError):
            services.submit_review(self.a, self.b_question.pk, self.review_values(), token)

    def test_stale_reveal_and_stale_save_rejected(self):
        initial = services.make_token(self.a, 'review', self.question)
        token = services.reveal_token(initial, self.a, self.question)
        services.save_question(self.a, self.question_values(content='已经编辑的新题目'), pk=self.question.pk)
        self.question.refresh_from_db()
        with self.assertRaises(ValidationError):
            services.reveal_token(initial, self.a, self.question)
        with self.assertRaises(ValidationError):
            services.submit_review(self.a, self.question.pk, self.review_values(), token)
        self.assertEqual(ReviewRecord.objects.count(), 0)

    def test_course_or_point_rename_invalidates_displayed_snapshot_version(self):
        token = self.review_token()
        services.save_point(self.a, self.course.pk, {'name': '键与参照完整性'}, pk=self.point.pk)
        with self.assertRaises(ValidationError):
            services.submit_review(self.a, self.question.pk, self.review_values(), token)
        self.question.refresh_from_db()
        token = self.review_token()
        services.save_course(self.a, {'name': '数据库课程新名称'}, pk=self.course.pk)
        with self.assertRaises(ValidationError):
            services.submit_review(self.a, self.question.pk, self.review_values(), token)

    def test_failure_after_record_insert_rolls_back_both(self):
        token = self.review_token()
        old_date = self.question.next_review_date
        with patch.object(WrongQuestion, 'save', side_effect=RuntimeError('simulated write failure')):
            with self.assertRaises(RuntimeError):
                services.submit_review(self.a, self.question.pk, self.review_values(), token)
        self.assertEqual(ReviewRecord.objects.count(), 0)
        self.question.refresh_from_db()
        self.assertEqual(self.question.next_review_date, old_date)

    def test_history_snapshot_unchanged_after_edit_and_archive(self):
        record, _ = services.submit_review(self.a, self.question.pk, self.review_values(), self.review_token())
        original = record.correct_answer_snapshot
        services.save_question(self.a, self.question_values(correct_answer='修改后的答案'), pk=self.question.pk)
        services.archive_question(self.a, self.question.pk, True)
        record.refresh_from_db()
        self.assertEqual(record.correct_answer_snapshot, original)
        self.assertEqual(record.knowledge_points_snapshot, ['主键与外键'])
        self.assertEqual(services.summary(self.a)['review_total'], 0)
        self.assertContains(self.client.get(f'/questions/{self.question.pk}/'), original)
        with self.assertRaises(ValidationError):
            record.save()
        with self.assertRaises(ValidationError):
            record.delete()
        with self.assertRaises(ValidationError):
            ReviewRecord.objects.filter(pk=record.pk).update(answer='覆盖')

    def test_mysql_history_immutable_even_raw_sql(self):
        if connection.vendor != 'mysql':
            self.skipTest('Requires actual MySQL triggers')
        record, _ = services.submit_review(self.a, self.question.pk, self.review_values(), self.review_token())
        for sql in ['UPDATE learning_reviewrecord SET answer=%s WHERE id=%s', 'DELETE FROM learning_reviewrecord WHERE id=%s']:
            with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(sql, ['修改', record.pk] if sql.startswith('UPDATE') else [record.pk])
        self.assertTrue(ReviewRecord.objects.filter(pk=record.pk).exists())

    def test_mysql_rejects_course_migration_even_raw_update(self):
        if connection.vendor != 'mysql':
            self.skipTest('Requires actual MySQL trigger')
        for model, obj in [(Task, self.task), (WrongQuestion, self.question), (KnowledgePoint, self.point)]:
            with self.subTest(model=model.__name__), self.assertRaises(DatabaseError), transaction.atomic():
                model.objects.filter(pk=obj.pk).update(course=self.other_course)

    def test_statistics_empty_denominator_and_counts(self):
        empty = services.summary(self.b, start=timezone.localdate(), end=timezone.localdate())
        self.assertEqual(empty['tasks_total'], 1)
        services.set_task_status(self.a, self.task.pk, True)
        services.submit_review(self.a, self.question.pk, self.review_values(), self.review_token())
        stats = services.summary(self.a)
        self.assertEqual((stats['tasks_total'], stats['tasks_done'], stats['completion_rate']), (1, 1, 100.0))
        self.assertEqual(stats['review_total'], 1)
        hard = next(row for row in stats['ratings'] if row['key'] == 'hard')
        self.assertEqual((hard['count'], hard['percent']), (1, 100.0))
        self.assertIsNone(services.summary(self.a, self.other_course.pk)['completion_rate'])
        row = next(row for row in stats['course_rows'] if row.pk == self.course.pk)
        self.assertEqual((row.task_total, row.task_done, row.question_total), (1, 1, 1))

    def test_date_range_changes_only_reviews_not_current_counts(self):
        services.submit_review(self.a, self.question.pk, self.review_values(), self.review_token())
        today = timezone.localdate()
        now = services.summary(self.a, start=today, end=today)
        past = services.summary(self.a, start=today - timedelta(days=30), end=today - timedelta(days=20))
        self.assertEqual((now['review_total'], past['review_total']), (1, 0))
        for field in ('tasks_total', 'tasks_done', 'tasks_pending', 'overdue', 'due_count'):
            self.assertEqual(now[field], past[field])

    def test_shanghai_day_boundary_half_open_utc_range(self):
        shanghai_date = timezone.localdate()
        begin, finish = services.date_interval(shanghai_date, shanghai_date)
        self.assertEqual(begin.hour, 16)
        self.assertEqual(finish - begin, timedelta(days=1))
        for index, stamp in enumerate([begin - timedelta(microseconds=1), begin,
            finish - timedelta(microseconds=1), finish]):
            ReviewRecord.objects.create(question=self.question, reviewed_at=stamp, review_date=shanghai_date,
                answer=str(index), rating='hard', note='', next_review_date=shanghai_date + timedelta(days=3),
                title_snapshot='历史', question_snapshot='题目', original_answer_snapshot='原答案',
                correct_answer_snapshot='答案', error_reason_snapshot='原因', course_snapshot=self.course.name,
                submission_key=uuid.uuid4())
        self.assertEqual(services.summary(self.a, start=shanghai_date, end=shanghai_date)['review_total'], 2)

    def test_local_today_and_due_at_utc_1600(self):
        with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 2, 15, 59, 59, tzinfo=dt_timezone.utc)):
            self.assertEqual(timezone.localdate().isoformat(), '2026-10-02')
        with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 2, 16, 0, 0, tzinfo=dt_timezone.utc)):
            self.assertEqual(timezone.localdate().isoformat(), '2026-10-03')

    def test_invalid_statistics_dates_and_pagination_query(self):
        response = self.client.get('/statistics/', {'start': '2026-10-05', 'end': '2026-10-01'})
        self.assertContains(response, '结束日期不能早于')
        self.assertIsNone(response.context['stats'])
        for index in range(22):
            Task.objects.create(course=self.course, title=f'分页任务{index}', due_date=timezone.localdate())
        response = self.client.get('/tasks/', {'course': self.course.pk, 'status': 'todo', 'page': '1'})
        self.assertContains(response, 'page=2')
        self.assertNotContains(response, 'href="??')
        self.assertContains(response, 'status=todo')

    def test_extreme_statistics_dates_are_friendly_errors_not_500(self):
        for value in ['0001-01-01', '9999-12-31', '1899-12-31', '2101-01-01']:
            with self.subTest(value=value):
                response = self.client.get('/statistics/', {'start': value, 'end': value})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '统计日期支持 1900-01-01 至 2100-12-31')
                self.assertIsNone(response.context['stats'])
                with self.assertRaises(ValidationError):
                    services.date_interval(date.fromisoformat(value), date.fromisoformat(value))
        for value in [services.MIN_STAT_DATE, services.MAX_STAT_DATE]:
            begin, end = services.date_interval(value, value)
            self.assertGreater(end, begin)
            response = self.client.get('/statistics/', {'start': value, 'end': value})
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(response.context['stats'])

    def test_question_text_20000_valid_20001_rejected_form_and_module(self):
        base = {'course': self.course.pk, 'title': '长度验证', 'content': '题目', 'original_answer': '原答案',
            'correct_answer': '答案', 'error_reason': '原因', 'knowledge_points': [], 'next_review_date': timezone.localdate()}
        for name in ('content', 'original_answer', 'correct_answer', 'error_reason'):
            with self.subTest(field=name):
                form = QuestionForm({**base, name: '文' * 20000}, user=self.a)
                self.assertTrue(form.is_valid(), form.errors)
                form = QuestionForm({**base, name: '文' * 20001}, user=self.a)
                self.assertFalse(form.is_valid())
                self.assertIn(name, form.errors)
                with self.assertRaises(ValidationError):
                    services.save_question(self.a, self.question_values(**{name: '文' * 20001}), token=services.make_token(self.a, 'question-create'))

    def test_review_answer_20000_valid_20001_rejected(self):
        token = self.review_token()
        for length, valid in [(20000, True), (20001, False)]:
            form = ReviewForm({'answer': '答' * length, 'rating': 'hard', 'token': token})
            self.assertEqual(form.is_valid(), valid)
        with self.assertRaises(ValidationError):
            services.submit_review(self.a, self.question.pk, self.review_values(answer='答' * 20001), token)
        record, _ = services.submit_review(self.a, self.question.pk, self.review_values(answer='答' * 20000), token)
        self.assertEqual(len(record.answer), 20000)

    def test_review_without_knowledge_points_and_note_limit(self):
        question = services.save_question(self.a, self.question_values(knowledge_points=[]), token=services.make_token(self.a, 'question-create'))
        token = self.review_token(question)
        with self.assertRaises(ValidationError):
            services.submit_review(self.a, question.pk, self.review_values(note='记' * 5001), token)
        record, _ = services.submit_review(self.a, question.pk, self.review_values(note='记' * 5000), token)
        self.assertEqual(record.knowledge_points_snapshot, [])
        self.assertEqual(len(record.note), 5000)

    def test_user_content_escaped(self):
        WrongQuestion.objects.filter(pk=self.question.pk).update(content='<script>alert(1)</script>')
        response = self.client.get(f'/questions/{self.question.pk}/')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')

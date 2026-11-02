"""Chart scopes and aggregation against real model constraints."""
import json
import uuid
from datetime import date, datetime, timedelta, timezone as utc
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from learning.analytics import learning_analytics
from learning.models import Course, KnowledgePoint, QuestionKnowledgePoint, ReviewRecord, Task, WrongQuestion


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LearningAnalyticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('chart-owner', password='Chart-2026!')
        cls.other = User.objects.create_user('chart-other')
        cls.course = Course.objects.create(owner=cls.owner, name='数据库')
        cls.second = Course.objects.create(owner=cls.owner, name='线性代数')
        cls.archived = Course.objects.create(owner=cls.owner, name='已归档课程', is_archived=True)
        cls.foreign = Course.objects.create(owner=cls.other, name='他人的课程')
        cls.question = cls.question_for(cls.course)
        cls.q_second = cls.question_for(cls.second)
        cls.q_archived = cls.question_for(cls.archived)
        cls.q_foreign = cls.question_for(cls.foreign)
        cls.q_hidden = cls.question_for(cls.course, is_archived=True)
        cls.point = KnowledgePoint.objects.create(course=cls.course, name='关系模型')
        QuestionKnowledgePoint.objects.create(question=cls.question, knowledge_point=cls.point)
        QuestionKnowledgePoint.objects.create(question=cls.q_hidden, knowledge_point=cls.point)

    @classmethod
    def question_for(cls, course, **kwargs):
        return WrongQuestion.objects.create(course=course, title='练习', content='题干', original_answer='原答',
            correct_answer='参考答案', error_reason='错因', next_review_date=date(2026, 10, 28), **kwargs)

    def record(self, question, stamp, rating='good'):
        local_day = (stamp + timedelta(hours=8)).date()
        return ReviewRecord.objects.create(question=question, reviewed_at=stamp, review_date=local_day,
            answer='作答', rating=rating, next_review_date=local_day+timedelta(days=1),
            title_snapshot=question.title, question_snapshot=question.content, original_answer_snapshot='原答',
            correct_answer_snapshot='答案', error_reason_snapshot='错因', course_snapshot=question.course.name,
            submission_key=uuid.uuid4())

    def analytics(self, course=None, start=date(2026, 10, 27), end=date(2026, 10, 27)):
        with patch('learning.analytics.timezone.localdate', return_value=date(2026, 10, 27)):
            return learning_analytics(self.owner, course, start, end)

    def test_owner_archive_and_course_filter_apply_to_all_charts(self):
        stamp = datetime(2026, 10, 27, 3, tzinfo=utc.utc)
        for q in (self.question, self.q_second, self.q_archived, self.q_foreign, self.q_hidden):
            self.record(q, stamp)
        result = self.analytics()
        self.assertEqual(result['review_total'], 2)
        self.assertEqual({r['id'] for r in result['courses']}, {self.course.pk, self.second.pk})
        self.assertEqual(result['points'][0]['count'], 1)
        self.assertEqual(sum(r['count'] for r in result['upcoming']), 2)
        self.assertEqual(self.analytics(self.course.pk)['review_total'], 1)
        self.assertEqual(self.analytics(self.foreign.pk)['courses'], [])

    def test_shanghai_midnight_boundaries_and_all_rating_buckets(self):
        # Selected local day is [previous day 16:00 UTC, current day 16:00 UTC).
        for stamp, rating in [(datetime(2026,10,26,15,59,59,tzinfo=utc.utc),'good'),
            (datetime(2026,10,26,16,tzinfo=utc.utc),'again'),
            (datetime(2026,10,27,2,tzinfo=utc.utc),'hard'),
            (datetime(2026,10,27,15,59,59,tzinfo=utc.utc),'good'),
            (datetime(2026,10,27,16,tzinfo=utc.utc),'good')]:
            self.record(self.question, stamp, rating)
        result = self.analytics()
        self.assertEqual(result['review_total'], 3)
        self.assertEqual(result['active_days'], 1)
        self.assertEqual(result['trend'][0]['count'], 3)
        self.assertEqual(result['heatmap'][0]['count'], 3)
        self.assertEqual([r['count'] for r in result['ratings']], [1, 1, 1])

    def test_tasks_partition_and_future_schedule_are_current_state(self):
        today = date(2026, 10, 27)
        for due, status in [(today-timedelta(days=1),'todo'),(today,'todo'),(today,'done')]:
            Task.objects.create(course=self.course, title='任务', due_date=due, status=status,
                completed_at=datetime(2026,10,27,tzinfo=utc.utc) if status=='done' else None)
        # Multiple linked questions and reviews must not multiply task counts.
        q = self.question_for(self.course)
        QuestionKnowledgePoint.objects.create(question=q, knowledge_point=self.point)
        for _ in range(3):
            self.record(self.question, datetime(2026,10,27,tzinfo=utc.utc))
        self.question.next_review_date=today-timedelta(days=1)
        self.question.save()
        self.q_second.next_review_date=today+timedelta(days=7)
        self.q_second.save()
        result = self.analytics(start=date(2020,1,1), end=date(2020,1,2))
        course = next(r for r in result['courses'] if r['id']==self.course.pk)
        self.assertEqual((course['done'],course['pending'],course['overdue'],course['total']), (1,1,1,3))
        self.assertEqual(result['points'][0]['count'], 2)
        self.assertEqual(result['review_total'], 0)
        self.assertEqual(result['overdue_questions'], 1)
        self.assertEqual(sum(r['count'] for r in result['upcoming']), 1)
        self.assertEqual(len(result['upcoming']), 7)

    def test_long_range_buckets_preserve_counts_and_bound_output(self):
        for year in (2020, 2023, 2026):
            self.record(self.question, datetime(year,1,1,tzinfo=utc.utc))
        result = self.analytics(start=date(2019,1,1), end=date(2028,12,28))
        self.assertLessEqual(len(result['trend']), 30)
        self.assertEqual(sum(r['count'] for r in result['trend']), 3)
        self.assertEqual(result['active_days'], 3)
        self.assertEqual(len(result['heatmap']), 84)
        self.assertEqual(result['trend'][0]['date'], '2019-01-01')
        self.assertEqual(result['trend'][-1]['end'], '2028-12-28')

    def test_empty_account_has_honest_zero_values(self):
        self.owner = User.objects.create_user('chart-empty')
        result = self.analytics()
        self.assertEqual(result['courses'], [])
        self.assertEqual(result['points'], [])
        self.assertEqual(result['review_total'], 0)
        self.assertEqual(result['active_days'], 0)
        self.assertTrue(all(r['count']==0 for r in result['ratings']+result['trend']+result['upcoming']))

    def test_statistics_get_is_read_only_and_chart_json_escapes_labels(self):
        unsafe = '</script><script>alert("chart")</script>'
        self.course.name=unsafe
        self.course.save()
        self.client.force_login(self.owner)
        before = (Task.objects.count(), WrongQuestion.objects.count(), ReviewRecord.objects.count())
        response = self.client.get('/statistics/', {'start':'2026-10-27','end':'2026-10-27'})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        payload = html.split('<script id="learning-analytics" type="application/json">',1)[1].split('</script>',1)[0]
        self.assertNotIn('<script>', payload)
        self.assertEqual(json.loads(payload)['courses'][0]['name'], unsafe)
        self.assertNotIn('他人的课程', html)
        self.assertEqual(before, (Task.objects.count(), WrongQuestion.objects.count(), ReviewRecord.objects.count()))
        self.assertEqual(html.count('data-chart='), 10)
        invalid = self.client.get('/statistics/', {'start':'2026-10-28','end':'2026-10-27'})
        self.assertIsNone(invalid.context['analytics'])
        self.assertNotContains(invalid, 'id="learning-analytics"')

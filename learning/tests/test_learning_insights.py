import io
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from learning import services
from learning.analytics import learning_analytics
from learning.example_curriculum import CURRICULUM
from learning.models import Course, KnowledgePoint, Task, WrongQuestion, ReviewRecord
from scheduling.models import SchedulingState, ScheduleEvent


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LearningInsightsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('insight-owner', password='Synthetic-test-only!')
        cls.other = User.objects.create_user('insight-other')
        cls.private = Course.objects.create(owner=cls.other, name='他人不可见的课程')
        call_command('seed_learning_examples', username=cls.owner.username,
            with_example_history=True, stdout=io.StringIO())

    def analytics(self, source='all', course=None):
        today=timezone.localdate()
        return learning_analytics(self.owner,course,today-timedelta(days=29),today,source)

    def counts(self):
        return tuple(model.objects.count() for model in (Course,KnowledgePoint,Task,WrongQuestion,ReviewRecord,SchedulingState,ScheduleEvent))

    def test_seed_has_expected_relations_and_explicit_example_provenance(self):
        self.assertEqual(Course.objects.filter(owner=self.owner).count(),7)
        self.assertEqual(KnowledgePoint.objects.filter(course__owner=self.owner).count(),28)
        self.assertEqual(Task.objects.filter(course__owner=self.owner).count(),28)
        self.assertEqual(WrongQuestion.objects.filter(course__owner=self.owner).count(),21)
        self.assertEqual(ReviewRecord.objects.filter(question__course__owner=self.owner,is_example=True).count(),63)
        self.assertEqual(SchedulingState.objects.filter(user=self.owner).count(),21)
        self.assertEqual(ScheduleEvent.objects.filter(state__user=self.owner).count(),63)
        self.assertFalse(Task.objects.filter(course__owner=self.owner,title__startswith='[示例]').exists())
        self.assertFalse(WrongQuestion.objects.filter(course__owner=self.owner,title__startswith='[示例]').exists())
        self.assertEqual(set(Course.objects.filter(owner=self.owner).values_list('name',flat=True)),{c['name'] for c in CURRICULUM})
        self.client.force_login(self.owner)
        course=self.client.get('/courses/').context['page_obj'][0]
        self.assertEqual((course.point_count,course.task_count,course.question_count),(4,4,3))

    def test_repeated_import_preserves_password_edits_and_history(self):
        before=self.counts()
        password=self.owner.password
        task=Task.objects.filter(course__owner=self.owner).first()
        task.title='本人修改过的任务';task.save(update_fields=['title'])
        call_command('seed_learning_examples',username=self.owner.username,with_example_history=True,stdout=io.StringIO())
        task.refresh_from_db();self.owner.refresh_from_db()
        self.assertEqual(self.counts(),before)
        self.assertEqual(task.title,'本人修改过的任务')
        self.assertEqual(self.owner.password,password)

    def test_personal_source_excludes_examples_without_inventing_predictions(self):
        result=self.analytics('personal')
        self.assertEqual(result['review_total'],0)
        self.assertEqual(result['example_reviews'],0)
        self.assertEqual(result['memory']['valid_count'],0)
        self.assertEqual(result['memory']['risks']['unknown'],21)
        self.assertEqual(result['memory']['cards'],[])
        self.assertEqual(result['memory']['hidden_count'],21)
        self.assertEqual(sum(sum(row['counts']) for row in result['rating_matrix']),0)
        # Content, current plans and instance relationships remain available.
        self.assertEqual(len(result['relationships']),7)
        self.assertEqual(len(result['workload']['dates']),14)

    def test_actual_review_of_example_question_stays_actual_and_model_is_mixed(self):
        question=WrongQuestion.objects.filter(course__owner=self.owner,
            next_review_date__lte=timezone.localdate()).first()
        token=services.reveal_token(services.make_token(self.owner,'review',question),self.owner,question)
        record,_=services.submit_review(self.owner,question.pk,{'answer':'本人在测试中实际提交的回答',
            'rating':'good','is_example':True},token)
        self.assertFalse(record.is_example)  # A form field cannot forge provenance.
        result=self.analytics('personal')
        self.assertEqual(result['review_total'],1)
        self.assertEqual(result['memory']['valid_count'],0)  # Prior example state still influences the model.
        self.assertEqual(self.analytics('example')['review_total'],63)
        self.assertEqual(services.summary(self.owner,start=timezone.localdate()-timedelta(days=29),
            end=timezone.localdate(),review_source='personal')['review_total'],1)

    def test_predictions_are_bounded_monotone_and_get_does_not_mutate_state(self):
        before=self.counts()
        result=self.analytics()
        self.assertEqual(result['memory']['valid_count'],21)
        self.assertEqual(sum(result['memory']['risks'].values()),21)
        priorities=[card['current'] for card in result['memory']['priority_cards']]
        self.assertEqual(priorities,sorted(priorities))
        for card in result['memory']['cards']:
            values=[p['value'] for p in card['points']]
            self.assertEqual(len(values),31)
            self.assertTrue(all(0<=v<=100 for v in values))
            self.assertTrue(all(a>=b for a,b in zip(values,values[1:])))
            self.assertTrue(card['example'])
        self.client.force_login(self.owner)
        response=self.client.get('/statistics/')
        self.assertContains(response,'初始化练习记录')
        self.assertNotContains(response,self.private.name)
        self.assertEqual(self.counts(),before)

    def test_bad_state_is_reported_without_reset_and_foreign_state_not_read(self):
        state=SchedulingState.objects.filter(user=self.owner).first()
        bad={**state.card_state,'difficulty':-1}
        SchedulingState.objects.filter(pk=state.pk).update(card_state=bad)
        result=self.analytics()
        self.assertEqual(result['memory']['invalid_count'],1)
        self.assertEqual(result['memory']['valid_count'],20)
        self.assertEqual(result['memory']['risks']['unknown'],1)
        state.refresh_from_db()
        self.assertEqual(state.card_state,bad)
        self.assertNotIn(self.private.name,str(result))

    def test_course_archive_filters_all_extended_views_and_workload(self):
        course=Course.objects.filter(owner=self.owner).first()
        result=self.analytics(course=course.pk)
        self.assertEqual(result['memory']['valid_count'],3)
        self.assertEqual(len(result['workload']['courses']),1)
        self.assertEqual(len(result['relationships']),1)
        self.assertEqual(len(result['relationships'][0]['points']),4)
        self.assertEqual(len(result['relationships'][0]['questions']),3)
        self.assertEqual(sum(sum(r['counts']) for r in result['rating_matrix']),9)
        services.archive_course(self.owner,course.pk,True)
        result=self.analytics()
        self.assertEqual(result['memory']['valid_count'],18)
        self.assertNotIn(course.pk,[r['id'] for r in result['relationships']])
        self.assertNotIn(course.pk,[r['id'] for r in result['workload']['courses']])

    def test_invalid_source_rejected_and_empty_account_is_honest(self):
        self.client.force_login(self.owner)
        response=self.client.get('/statistics/',{'start':timezone.localdate(),'end':timezone.localdate(),'review_source':'invalid'})
        self.assertIsNone(response.context['analytics'])
        self.owner=self.other
        result=self.analytics('personal')
        self.assertEqual(result['memory']['cards'],[])
        self.assertEqual(result['memory']['risks']['unknown'],0)
        self.assertEqual(result['workload']['courses'][0]['days'],[{'tasks':0,'questions':0}]*14)

    def test_import_failure_and_dry_run_roll_back_everything(self):
        fresh=User.objects.create_user('insight-dry-run')
        before=self.counts()
        call_command('seed_learning_examples',username=fresh.username,with_example_history=True,dry_run=True,stdout=io.StringIO())
        self.assertEqual(self.counts(),before)
        Course.objects.create(owner=fresh,name=CURRICULUM[-1]['name'],is_archived=True)
        before=self.counts()
        with self.assertRaises(CommandError):
            call_command('seed_learning_examples',username=fresh.username,with_example_history=True,stdout=io.StringIO())
        self.assertEqual(self.counts(),before)

    def test_content_only_mode_never_generates_performance_history(self):
        fresh=User.objects.create_user('insight-content-only')
        call_command('seed_learning_examples',username=fresh.username,stdout=io.StringIO())
        self.assertEqual(WrongQuestion.objects.filter(course__owner=fresh).count(),21)
        self.assertFalse(ReviewRecord.objects.filter(question__course__owner=fresh).exists())
        self.assertFalse(SchedulingState.objects.filter(user=fresh).exists())

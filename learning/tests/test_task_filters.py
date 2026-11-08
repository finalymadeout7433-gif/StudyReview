from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from learning.models import Course, Task


class TaskFilterTests(TestCase):
    def setUp(self):
        user=get_user_model().objects.create_user('task-filter-owner')
        other=get_user_model().objects.create_user('task-filter-other')
        self.course=Course.objects.create(owner=user,name='数据库')
        other_course=Course.objects.create(owner=other,name='其他用户课程')
        today=timezone.localdate()
        for name,days in [('昨天',-1),('今天',0),('第七天',6),('第八天',7)]:
            Task.objects.create(course=self.course,title=name,description='SQL练习',due_date=today+timedelta(days=days))
        Task.objects.create(course=other_course,title='他人的SQL',due_date=today)
        self.client.force_login(user)

    def test_today_and_seven_day_boundaries(self):
        response=self.client.get('/tasks/?status=today')
        self.assertEqual([x.title for x in response.context['page_obj']],['今天'])
        response=self.client.get('/tasks/?status=upcoming')
        self.assertEqual([x.title for x in response.context['page_obj']],['今天','第七天'])

    def test_keyword_filters_notes_and_preserves_owner_scope(self):
        response=self.client.get('/tasks/?q=SQL&status=upcoming')
        self.assertEqual(response.context['page_obj'].paginator.count,2)
        self.assertNotContains(response,'他人的SQL')
        self.assertEqual(self.client.get('/tasks/?q=没有此项').context['page_obj'].paginator.count,0)

    def test_statistics_course_link_defaults_to_thirty_days(self):
        response=self.client.get('/statistics/',{'course':self.course.pk})
        self.assertIsNotNone(response.context['stats'])
        self.assertEqual(response.context['stats']['start'],timezone.localdate()-timedelta(days=29))
        invalid=self.client.get('/statistics/',{'course':self.course.pk,'start':''})
        self.assertIsNone(invalid.context['stats'])

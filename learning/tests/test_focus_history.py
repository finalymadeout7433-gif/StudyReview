from datetime import datetime,timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from learning.focus import command
from learning.focus_history import time_buckets, HistoryFilter, filtered_history
from learning.models import Course,Task,FocusSession

class FocusHistoryTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('history-owner')
        self.other=get_user_model().objects.create_user('history-other')
        self.course=Course.objects.create(owner=self.user,name='历史课程')
        self.start=timezone.make_aware(datetime(2026,11,3,23,50,0,500000))
        self.client.force_login(self.user)
    def test_cross_midnight_exact_week_total_and_pause(self):
        s=command(self.user,'start',course_id=self.course.pk,now=self.start)
        command(self.user,'finish',s.pk,now=self.start+timedelta(minutes=25))
        days=time_buckets(self.user,self.start.date(),2,now=self.start+timedelta(days=1))
        self.assertEqual([r['seconds'] for r in days],[599,900])
        self.assertEqual(sum(r['microseconds'] for r in days),1500*1000000)
        s=command(self.user,'start',now=self.start+timedelta(hours=1))
        command(self.user,'pause',s.pk,now=self.start+timedelta(hours=1,minutes=2))
        command(self.user,'resume',s.pk,now=self.start+timedelta(hours=2))
        command(self.user,'finish',s.pk,now=self.start+timedelta(hours=2,minutes=3))
        days=time_buckets(self.user,self.start.date(),2,now=self.start+timedelta(days=1))
        self.assertEqual(sum(r['microseconds'] for r in days),1800*1000000)
    def test_filters_pagination_invalid_and_foreign(self):
        for i in range(14):
            s=command(self.user,'start',course_id=self.course.pk,now=self.start+timedelta(minutes=i))
            command(self.user,'finish',s.pk,now=self.start+timedelta(minutes=i,seconds=10))
        r=self.client.get('/focus/',{'history_course':self.course.pk})
        self.assertEqual(len(r.context['history']),12)
        self.assertEqual(r.context['history_page'].paginator.count,14)
        self.assertEqual(len(self.client.get('/focus/',{'history_course':self.course.pk,'history_page':2}).context['history']),2)
        r=self.client.get('/focus/',{'history_start':'2026-11-05','history_end':'2026-11-01'})
        self.assertTrue(r.context['history_form'].errors);self.assertEqual(len(r.context['history']),0)
        foreign=Course.objects.create(owner=self.other,name='其他账号')
        r=self.client.get('/focus/',{'history_course':foreign.pk})
        self.assertTrue(r.context['history_form'].errors)
        self.assertEqual(time_buckets(self.other,self.start.date(),7)[0]['seconds'],0)
    def test_deleted_task_and_archived_course_keep_statistics(self):
        task=Task.objects.create(course=self.course,title='删除后保留投入',due_date=self.start.date())
        s=command(self.user,'start',task_id=task.pk,now=self.start)
        command(self.user,'finish',s.pk,now=self.start+timedelta(seconds=30))
        task.delete();self.course.is_archived=True;self.course.save()
        form=HistoryFilter({'history_course':str(self.course.pk)},user=self.user)
        self.assertEqual(filtered_history(self.user,form).count(),1)
        self.assertEqual(time_buckets(self.user,self.start.date(),1)[0]['seconds'],30)
    def test_empty_and_query_count(self):
        s=command(self.user,'start',now=self.start)
        command(self.user,'finish',s.pk,now=self.start+timedelta(minutes=5))
        with self.assertNumQueries(2):
            rows=time_buckets(self.user,self.start.date(),7)
        self.assertEqual(len(rows),7)
        self.assertEqual(time_buckets(self.other,self.start.date(),7),[dict(row,seconds=0,microseconds=0,minutes=0,label='0分00秒') for row in rows])
        self.assertEqual(self.client.get('/focus/',{'history_course':'free'}).context['history_page'].paginator.count,1)

    def test_subsecond_activity_is_not_mislabeled_as_no_record(self):
        now=timezone.now()-timedelta(seconds=2)
        s=command(self.user,'start',now=now)
        command(self.user,'finish',s.pk,now=now+timedelta(microseconds=500000))
        response=self.client.get('/focus/state/').json()
        self.assertEqual(response['week_minutes'],0)
        self.assertEqual(response['week_active_days'],1)

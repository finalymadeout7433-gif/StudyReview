from datetime import datetime,timedelta,date
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from learning.models import Course
from learning.focus import command
from learning.focus_daily import daily_breakdown
from learning.focus_history import time_buckets

class DailyFocusTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('daily-owner');self.other=get_user_model().objects.create_user('daily-other')
        self.course=Course.objects.create(owner=self.user,name='数据库');self.second=Course.objects.create(owner=self.user,name='数学')
        self.start=timezone.make_aware(datetime(2026,11,3,23,50));self.client.force_login(self.user)
    def session(self,course,start,minutes):
        s=command(self.user,'start',course_id=course.pk if course else None,now=start)
        command(self.user,'finish',s.pk,now=start+timedelta(minutes=minutes));return s
    def test_single_subject_full_circle_and_empty(self):
        self.session(self.course,self.start,5)
        d=daily_breakdown(self.user,self.start.date(),self.start+timedelta(days=1))
        self.assertEqual(d['groups'][0]['percent'],'100.0');self.assertEqual(d['total_microseconds'],300000000)
        self.assertIn('360.00000000deg',d['gradient']);self.assertEqual(len(d['records']),1)
        self.assertEqual(daily_breakdown(self.other,self.start.date())['groups'],[])
    def test_cross_day_pause_free_focus_and_exact_totals(self):
        s=command(self.user,'start',course_id=self.course.pk,now=self.start)
        command(self.user,'pause',s.pk,now=self.start+timedelta(minutes=5))
        command(self.user,'resume',s.pk,now=self.start+timedelta(minutes=15))
        command(self.user,'finish',s.pk,now=self.start+timedelta(minutes=20))
        self.session(self.second,self.start+timedelta(hours=1),10)
        self.session(None,self.start+timedelta(hours=2),5)
        now=self.start+timedelta(days=1);day=self.start.date()+timedelta(days=1)
        d=daily_breakdown(self.user,day,now)
        self.assertEqual(d['total_microseconds'],1200000000)
        self.assertEqual({r['name']:r['percent'] for r in d['groups']},{'数据库':'25.0','数学':'50.0','自由专注':'25.0'})
        self.assertEqual(len(set(r['color'] for r in d['groups'])),3)
        self.assertEqual(d['total_microseconds'],time_buckets(self.user,day,1,now)[0]['microseconds'])
        self.assertEqual(daily_breakdown(self.user,self.start.date(),now)['total_microseconds'],300000000)
    def test_target_cap_and_open_session(self):
        command(self.user,'start',course_id=self.course.pk,now=self.start)
        d=daily_breakdown(self.user,self.start.date()+timedelta(days=1),self.start+timedelta(hours=3))
        self.assertEqual(d['total_microseconds'],900000000)
    def test_subsecond_and_percent_rounding(self):
        for i,c in enumerate([self.course,self.second,None]):
            s=command(self.user,'start',course_id=c.pk if c else None,now=self.start+timedelta(seconds=i))
            command(self.user,'finish',s.pk,now=self.start+timedelta(seconds=i,microseconds=100000))
        d=daily_breakdown(self.user,self.start.date(),self.start+timedelta(days=1))
        self.assertEqual(d['total_duration'],'不足1秒');self.assertEqual(sum(float(r['percent']) for r in d['groups']),100)
    def test_archived_course_and_deleted_task_trace_kept(self):
        self.session(self.course,self.start,5);self.course.is_archived=True;self.course.save()
        self.assertEqual(daily_breakdown(self.user,self.start.date())['groups'][0]['name'],'数据库')
    def test_calendar_invalid_date_and_pagination(self):
        for i in range(14):self.session(self.course,self.start-timedelta(hours=i),1)
        r=self.client.get('/focus/',{'day':'2026-11-03'})
        self.assertEqual(r.context['daily_page'].paginator.count,14);self.assertEqual(len(r.context['daily_page']),12)
        self.assertNotContains(r,'name="history_start"');self.assertContains(r,'选择日期')
        r=self.client.get('/focus/',{'day':'2026-11-03','day_page':2});self.assertEqual(len(r.context['daily_page']),2)
        r=self.client.get('/focus/',{'day':'9999-01-01'});self.assertTrue(r.context['day_error']);self.assertEqual(r.context['daily']['groups'],[])
        r=self.client.get('/focus/',{'month':'invalid'});self.assertTrue(r.context['day_error'])

    def test_month_limits_recover_without_calendar_overflow(self):
        for month in ('0001-01','9999-12','1899-12','2101-01'):
            with self.subTest(month=month):
                r=self.client.get('/focus/',{'day':'2026-11-04','month':month})
                self.assertEqual(r.status_code,200)
                self.assertTrue(r.context['day_error'])
                self.assertEqual(r.context['calendar_month'],date(2026,11,1))
                self.assertEqual(r.context['daily']['groups'],[])
        for day in ('1900-01-01','2100-12-31'):
            with self.subTest(day=day):
                r=self.client.get('/focus/',{'day':day})
                self.assertEqual(r.status_code,200)
                self.assertFalse(r.context['day_error'])

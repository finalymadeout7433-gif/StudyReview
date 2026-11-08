from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction, connection
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from learning.focus import command
from learning.focus_daily import daily_breakdown
from learning.models import Course, Task
from learning.services import delete_task


class DailyFocusEdgeTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('synthetic_daily_edges')
        self.other=get_user_model().objects.create_user('synthetic_daily_edges_other')
        self.course=Course.objects.create(owner=self.user,name='同名课程')
        self.start=timezone.make_aware(datetime(2026,11,3,10))
        self.client.force_login(self.user)

    def record(self,course,offset=0,seconds=10,user=None,task=None):
        user=user or self.user
        start=self.start+timedelta(seconds=offset)
        s=command(user,'start',course_id=course.pk if course else None,
                  task_id=task.pk if task else None,now=start)
        command(user,'finish',s.pk,now=start+timedelta(seconds=seconds))
        return s

    def test_equal_course_names_are_unique_per_owner_and_isolated(self):
        with self.assertRaises(IntegrityError),transaction.atomic():
            Course.objects.create(owner=self.user,name=self.course.name)
        foreign=Course.objects.create(owner=self.other,name=self.course.name)
        self.record(self.course);self.record(foreign,seconds=90,user=self.other)
        result=daily_breakdown(self.user,self.start.date())
        self.assertEqual(result['total_microseconds'],10_000_000)
        self.assertEqual([g['course_id'] for g in result['groups']],[self.course.pk])

    def test_course_named_free_focus_is_distinguishable_from_unlinked_focus(self):
        named=Course.objects.create(owner=self.user,name='自由专注')
        self.record(named);self.record(None,offset=60)
        response=self.client.get('/focus/',{'day':self.start.date().isoformat()})
        groups=response.context['daily']['groups']
        self.assertEqual([g['name'] for g in groups],['自由专注','自由专注'])
        self.assertEqual(len({g['course_id'] for g in groups}),2)
        html=response.content.decode()
        self.assertTrue('未关联课程' in html)
        self.assertTrue('课程专注' in html)

    def test_more_than_palette_short_sessions_and_percent_total(self):
        for i in range(12):
            course=Course.objects.create(owner=self.user,name=f'合成学科{i+1:02d}')
            self.record(course,offset=i*60,seconds=i+1)
        self.record(None,offset=12*60,seconds=13)
        result=daily_breakdown(self.user,self.start.date())
        self.assertEqual(len(result['groups']),13)
        self.assertEqual(len({g['color'] for g in result['groups']}),13)
        self.assertEqual(sum(Decimal(g['percent']) for g in result['groups']),Decimal('100.0'))
        self.assertEqual(sum(g['microseconds'] for g in result['groups']),91_000_000)
        self.assertEqual(result['total_duration'],'1分31秒')
        self.assertEqual({g['duration'] for g in result['groups']},{f'0分{i:02d}秒' for i in range(1,14)})

    def test_deleted_task_snapshot_archived_course_and_deletion_protection(self):
        task=Task.objects.create(course=self.course,title='应保留的任务标题',due_date=self.start.date())
        session=self.record(self.course,task=task,seconds=25)
        delete_task(self.user,task.pk)
        session.refresh_from_db();self.assertIsNone(session.task_id)
        self.assertEqual(session.task_title,'应保留的任务标题')
        self.course.is_archived=True;self.course.save(update_fields=['is_archived'])
        with self.assertRaises(ProtectedError):self.course.delete()
        if connection.vendor=='mysql':
            with self.assertRaises(IntegrityError),transaction.atomic():
                with connection.cursor() as c:c.execute('DELETE FROM learning_course WHERE id=%s',[self.course.pk])
        response=self.client.get('/focus/',{'day':self.start.date().isoformat()})
        self.assertEqual(response.context['daily']['total_microseconds'],25_000_000)
        self.assertEqual(response.context['daily']['records'][0]['task'],'应保留的任务标题')
        html=response.content.decode()
        self.assertTrue('任务已删除' in html)
        self.assertTrue('已归档课程' in html)

    def test_utc_storage_is_split_at_beijing_midnight_not_utc_midnight(self):
        self.assertEqual(timezone.get_current_timezone_name(),'Asia/Shanghai')
        utc_start=datetime(2026,11,3,15,59,30,tzinfo=dt_timezone.utc)
        s=command(self.user,'start',course_id=self.course.pk,now=utc_start.astimezone(ZoneInfo('Asia/Tokyo')))
        command(self.user,'finish',s.pk,now=utc_start+timedelta(seconds=60))
        s.refresh_from_db();self.assertEqual(s.started_at,utc_start)
        for day in (datetime(2026,11,3).date(),datetime(2026,11,4).date()):
            result=daily_breakdown(self.user,day,utc_start+timedelta(days=2))
            self.assertEqual(result['total_microseconds'],30_000_000)
        response=self.client.get('/focus/',{'day':'2026-11-04'})
        self.assertEqual(response.context['daily']['total_duration'],'0分30秒')
        html=response.content.decode()
        self.assertTrue('11月03日 23:59' in html and '11月04日 00:00' in html)

    def test_record_paging_preserves_full_day_total_and_has_no_missing_rows(self):
        ids=[self.record(self.course,offset=i*60,seconds=1).pk for i in range(25)]
        found=[]
        for page,count in ((1,12),(2,12),(3,1)):
            response=self.client.get('/focus/',{'day':'2026-11-03','day_page':page})
            records=response.context['daily_page']
            self.assertEqual(len(records),count)
            self.assertEqual(response.context['daily']['total_microseconds'],25_000_000)
            self.assertEqual(response.context['day'].isoformat(),'2026-11-03')
            found.extend(r['id'] for r in records)
        self.assertEqual(found,list(reversed(ids)))
        for invalid,expected_page in (('invalid',1),('-1',3),('9999',3)):
            response=self.client.get('/focus/',{'day':'2026-11-03','day_page':invalid})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.context['daily_page'].number,expected_page)

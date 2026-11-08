from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db import connection, transaction, DatabaseError
from django.http import Http404
from django.test import TestCase
from django.utils import timezone
from learning.models import Course, Task, FocusSession
from learning.focus import command

class FocusContextTests(TestCase):
    def test_dashboard_active_focus_is_owned_and_finished_is_not_active(self):
        self.assertNotContains(self.client.get('/'), '复习已清空')
        session=command(self.user,'start',task_id=self.task.pk)
        response=self.client.get('/')
        self.assertEqual(response.context['active_focus'],session)
        self.assertContains(response,'返回当前专注')
        command(self.user,'pause',session.pk)
        self.assertContains(self.client.get('/'),'专注已暂停')
        self.client.force_login(self.other)
        self.assertIsNone(self.client.get('/').context['active_focus'])
        self.assertNotContains(self.client.get('/'),self.task.title)
        free=command(self.other,'start')
        self.assertContains(self.client.get('/'),'自由专注')
        command(self.other,'finish',free.pk)
        self.assertIsNone(self.client.get('/').context['active_focus'])

    def setUp(self):
        self.user=get_user_model().objects.create_user('focus-context')
        self.other=get_user_model().objects.create_user('focus-context-other')
        self.course=Course.objects.create(owner=self.user,name='测试课程')
        self.task=Task.objects.create(course=self.course,title='验证任务',due_date=timezone.localdate())
        self.client.force_login(self.user)

    def test_course_and_task_prefill_and_completion_independent(self):
        r=self.client.get('/focus/',{'course':self.course.pk})
        self.assertEqual(r.context['selected_course'],self.course)
        r=self.client.get('/focus/',{'task':self.task.pk})
        self.assertEqual(r.context['selected_task'],self.task)
        s=command(self.user,'start',task_id=self.task.pk)
        self.assertEqual(s.task_id,self.task.pk);self.assertEqual(s.course_id,self.course.pk)
        command(self.user,'finish',s.pk)
        self.task.refresh_from_db();self.assertEqual(self.task.status,'todo')

    def test_deleted_task_retains_focus_history_and_title(self):
        s=command(self.user,'start',task_id=self.task.pk)
        command(self.user,'finish',s.pk)
        self.task.title='后来修改';self.task.save()
        self.task.delete();s.refresh_from_db()
        self.assertIsNone(s.task_id);self.assertEqual(s.task_title,'验证任务')
        self.assertContains(self.client.get('/focus/'),'验证任务')

    def test_foreign_and_archived_context_rejected(self):
        with self.assertRaises(Http404):command(self.other,'start',task_id=self.task.pk)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/focus/',{'task':self.task.pk}).status_code,404)
        self.course.is_archived=True;self.course.save()
        with self.assertRaises(Http404):command(self.user,'start',task_id=self.task.pk)

    def test_export_version_scope_intervals_and_account_isolation(self):
        now=timezone.now();s=command(self.user,'start',task_id=self.task.pk,now=now)
        command(self.user,'pause',s.pk,now=now+timedelta(seconds=12))
        result=self.client.get('/focus/export/')
        data=result.json()
        self.assertEqual(data['format'],'studyreview.focus');self.assertEqual(data['version'],1)
        self.assertEqual(data['sessions'][0]['task_id'],self.task.pk)
        self.assertEqual(len(data['intervals']),1)
        from datetime import datetime
        interval=data['intervals'][0]
        self.assertEqual((datetime.fromisoformat(interval['ended_at'])-datetime.fromisoformat(interval['started_at'])).total_seconds(),12)
        self.assertNotIn('owner',data);self.assertNotIn('password',result.content.decode())
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/focus/export/').json()['sessions'],[])

    def test_database_task_course_guard(self):
        if connection.vendor!='mysql':self.skipTest('MySQL trigger')
        wrong=Course.objects.create(owner=self.user,name='其他课程')
        with self.assertRaises(DatabaseError),transaction.atomic():
            FocusSession.objects.create(owner=self.user,course=wrong,task=self.task)

    def test_native_export_isolated_non_overwriting_and_requires_post_csrf(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from django.test import Client
        command(self.user,'start',task_id=self.task.pk)
        command(self.other,'start')
        with TemporaryDirectory() as directory,self.settings(DESKTOP_NATIVE=True,PRIVATE_DATA_ROOT=Path(directory)):
            self.assertContains(self.client.get('/focus/'),'保存专注记录到本机（JSON）')
            self.assertEqual(self.client.get('/focus/export/local/').status_code,405)
            csrf_client=Client(enforce_csrf_checks=True);csrf_client.force_login(self.user)
            self.assertEqual(csrf_client.post('/focus/export/local/').status_code,403)
            first=self.client.post('/focus/export/local/')
            self.assertEqual(first.status_code,200)
            path=Path(first.context['export_path'])
            self.assertEqual(path.parent,Path(directory)/'exports'/str(self.user.pk))
            original=path.read_bytes();data=json.loads(original)
            self.assertEqual(len(data['sessions']),1)
            self.assertEqual(data['sessions'][0]['task_id'],self.task.pk)
            self.assertNotIn('password',original.decode())
            second=self.client.post('/focus/export/local/')
            self.assertNotEqual(second.context['export_path'],str(path))
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(first['Cache-Control'],'no-store')
        with self.settings(DESKTOP_NATIVE=False):
            self.assertEqual(self.client.post('/focus/export/local/').status_code,404)

    def test_native_export_write_failure_is_actionable_and_preserves_records(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        command(self.user,'start')
        with TemporaryDirectory() as directory,self.settings(DESKTOP_NATIVE=True,PRIVATE_DATA_ROOT=Path(directory)):
            (Path(directory)/'exports').write_text('existing non-directory file')
            response=self.client.post('/focus/export/local/')
            self.assertContains(response,'专注记录仍保留在数据库中',status_code=503)
            self.assertEqual(FocusSession.objects.filter(owner=self.user).count(),1)

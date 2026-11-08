from datetime import datetime, timedelta
from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from learning.models import Course, FocusSession, FocusInterval
from learning.focus import command, seconds, daily_seconds


class FocusTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('focus-owner')
        self.other=get_user_model().objects.create_user('focus-other')
        self.course=Course.objects.create(owner=self.user,name='专注测试课程')
        self.now=timezone.make_aware(datetime(2026,11,4,12))

    def start(self):
        return command(self.user,'start',course_id=self.course.pk,now=self.now)

    def test_pause_resume_and_repeat_end(self):
        s=self.start()
        command(self.user,'pause',s.pk,now=self.now+timedelta(minutes=5))
        command(self.user,'resume',s.pk,now=self.now+timedelta(minutes=15))
        command(self.user,'resume',s.pk,now=self.now+timedelta(minutes=16))
        command(self.user,'finish',s.pk,now=self.now+timedelta(minutes=20))
        command(self.user,'finish',s.pk,now=self.now+timedelta(hours=2))
        s.refresh_from_db()
        self.assertEqual(seconds(s,self.now+timedelta(hours=2)),600)
        self.assertEqual(s.intervals.count(),2)
        self.assertEqual(s.status,'finished')

    def test_duplicate_start_and_target_cap(self):
        s=self.start()
        self.assertEqual(command(self.user,'start',now=self.now).pk,s.pk)
        s=command(self.user,'finish',s.pk,now=self.now+timedelta(hours=8))
        self.assertEqual(seconds(s,self.now+timedelta(hours=8)),1500)

    def test_cross_midnight_splits_and_excludes_pause(self):
        start=timezone.make_aware(datetime(2026,11,4,23,50))
        s=command(self.user,'start',now=start)
        command(self.user,'pause',s.pk,now=start+timedelta(minutes=5))
        command(self.user,'resume',s.pk,now=start+timedelta(minutes=15))
        command(self.user,'finish',s.pk,now=start+timedelta(minutes=25))
        self.assertEqual(daily_seconds(self.user,start.date()),300)
        self.assertEqual(daily_seconds(self.user,(start+timedelta(days=1)).date()),600)

    def test_foreign_course_and_session_rejected(self):
        s=self.start()
        with self.assertRaises(Http404):command(self.other,'finish',s.pk)
        with self.assertRaises(Http404):command(self.other,'start',course_id=self.course.pk)
        self.assertEqual(daily_seconds(self.other,self.now.date()),0)

    def test_archived_course_rejected_and_invalid_duration(self):
        self.course.is_archived=True;self.course.save()
        with self.assertRaises(Http404):self.start()
        with self.assertRaises(ValueError):command(self.user,'start',minutes=-1)

    def test_pages_and_post_redirect_get(self):
        self.assertEqual(self.client.get(reverse('focus')).status_code,302)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('focus')),'开始专注')
        self.client.post(reverse('focus'),{'action':'start','minutes':25})
        self.assertEqual(FocusSession.objects.filter(owner=self.user).count(),1)
        for _ in range(2):self.assertContains(self.client.get(reverse('focus')),'暂停专注')
        self.assertEqual(FocusInterval.objects.count(),1)
        self.assertContains(self.client.get(reverse('dashboard')),'返回当前专注')

    def test_csrf_required(self):
        from django.test import Client
        client=Client(enforce_csrf_checks=True);client.force_login(self.user)
        self.assertEqual(client.post(reverse('focus'),{'action':'start'}).status_code,403)

    def test_database_blocks_second_active_and_cross_owner(self):
        from django.db import DatabaseError, transaction, connection
        self.start()
        with self.assertRaises(DatabaseError), transaction.atomic():
            FocusSession.objects.create(owner=self.user)
        if connection.vendor=='mysql':
            with self.assertRaises(DatabaseError), transaction.atomic():
                FocusSession.objects.create(owner=self.other,course=self.course)

    def test_auto_completion_needs_server_deadline(self):
        s=self.start()
        command(self.user,'complete',s.pk,now=self.now+timedelta(seconds=1))
        s.refresh_from_db();self.assertEqual(s.status,'running')
        command(self.user,'complete',s.pk,now=self.now+timedelta(minutes=25))
        s.refresh_from_db();self.assertEqual(s.status,'finished')
        self.assertEqual(seconds(s,self.now+timedelta(days=1)),1500)

    def test_state_is_private_uncached_and_read_only(self):
        self.start();self.client.force_login(self.other)
        response=self.client.get(reverse('focus-state'))
        self.assertIsNone(response.json()['session'])
        self.assertEqual(response['Cache-Control'],'no-store')
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('focus-state')).json()['status'],'running')
        self.assertEqual(FocusInterval.objects.count(),1)

    def test_short_session_keeps_seconds_visible(self):
        s=self.start()
        command(self.user,'finish',s.pk,now=self.now+timedelta(seconds=2))
        self.client.force_login(self.user)
        response=self.client.get(reverse('focus'),{'day':self.now.date().isoformat()})
        self.assertEqual(response.context['daily']['total_microseconds'],2000000)
        self.assertContains(response,'0分02秒')

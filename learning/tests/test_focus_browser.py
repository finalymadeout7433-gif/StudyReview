"""Opt-in real HTTP/browser checks. Never use a real learning account."""
import os
import socket
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path
from urllib.request import urlopen
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from learning.models import Course, Task, FocusSession, FocusInterval
from learning.focus import seconds


@unittest.skipUnless(os.environ.get('STUDY_RUN_FOCUS_BROWSER') == '1', 'Opt-in real browser test')
class FocusBrowserTests(TransactionTestCase):
    def _fixture_teardown(self):
        if connection.vendor=='mysql':
            name=connection.settings_dict['NAME']
            if name!=settings.DATABASES['default']['TEST']['NAME'] or name not in settings.AUTHORIZED_MIGRATION_SCHEMAS or not name.startswith('test_study_review_v2_'):
                raise RuntimeError('Refusing browser-fixture cleanup outside the exact synthetic test schema.')
            with connection.cursor() as c:
                c.execute('SET FOREIGN_KEY_CHECKS=0')
                try:
                    for table in ('attachments_reviewimagesnapshot','attachments_reviewimagemanifest','scheduling_scheduleevent','learning_reviewrecord'):
                        c.execute('TRUNCATE TABLE '+table)
                finally:c.execute('SET FOREIGN_KEY_CHECKS=1')
        TransactionTestCase._fixture_teardown(self)
    def capture(self,page,name):
        directory=Path(settings.BASE_DIR).parent/'round3-evidence'
        directory.mkdir(exist_ok=True)
        page.screenshot(path=str(directory/(name+'.png')),full_page=True)
    def db(self, operation):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connections
        def run():
            try:return operation()
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(run).result()
    def setUp(self):
        assert connection.settings_dict['NAME'] == settings.DATABASES['default']['TEST']['NAME']
        assert connection.settings_dict['NAME'].startswith('test_study_review_v2_')
        self.password=uuid.uuid4().hex
        self.user=get_user_model().objects.create_user('synthetic_focus_browser',password=self.password)
        self.course=Course.objects.create(owner=self.user,name='浏览器专注测试')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
        self.server=None
        self.start_server()

    def start_server(self):
        env=os.environ.copy()
        env['STUDY_FOCUS_BROWSER_DB']=connection.settings_dict['NAME']
        self.server=subprocess.Popen([sys.executable,'manage.py','runserver',f'127.0.0.1:{self.port}','--noreload','--settings=config.focus_browser_test_settings'],cwd=settings.BASE_DIR,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(100):
            try:
                with urlopen(f'http://127.0.0.1:{self.port}/health/',timeout=.3) as response:
                    if response.status==200:return
            except Exception:time.sleep(.1)
        self.fail('Synthetic HTTP server did not become ready')

    def stop_server(self):
        if self.server:
            self.server.terminate();self.server.wait(timeout=10);self.server=None

    def tearDown(self):
        self.stop_server()

    def test_start_is_discoverable_and_rest_returns_keyboard_focus(self):
        from playwright.sync_api import sync_playwright, expect
        task=Task.objects.create(course=self.course,title='Synthetic focus task',due_date=timezone.localdate())
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context()
            page=context.new_page();base=f'http://127.0.0.1:{self.port}'
            page.goto(base+'/focus/')
            page.locator('[name=username]').fill(self.user.username)
            page.locator('[name=password]').fill(self.password)
            page.locator('button[type=submit]').click()
            page.wait_for_url('**/focus/')
            for width,height in [(1280,880),(1280,720),(390,844)]:
                page.set_viewport_size({'width':width,'height':height})
                for suffix in ['',f'?task={task.pk}']:
                    page.goto(base+'/focus/'+suffix)
                    button=page.locator('.focus-start button[type=submit]')
                    evidence=Path(settings.BASE_DIR).parent/'round8-evidence'
                    evidence.mkdir(exist_ok=True)
                    page.screenshot(path=str(evidence/f'start-{width}-{height}-{bool(suffix)}.png'),full_page=True)
                    box=button.bounding_box()
                    self.assertGreaterEqual(box['y'],0)
                    self.assertLessEqual(box['y']+box['height'],height,(width,height,suffix,box))
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            page.get_by_role('button',name='休息 5 分钟',exact=True).click()
            page.get_by_role('button',name='结束休息，准备学习',exact=True).click()
            expect(page.locator('[name=minutes]:checked')).to_be_focused()
            browser.close()

    def test_restart_refresh_early_finish_and_duplicate_post(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000})
            page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            base=f'http://127.0.0.1:{self.port}'
            page.goto(base+'/focus/')
            page.locator('[name=username]').fill(self.user.username)
            page.locator('[name=password]').fill(self.password)
            page.locator('button[type=submit]').click()
            page.wait_for_url('**/focus/')
            page.locator('#focus-course').select_option(str(self.course.pk))
            page.get_by_role('button',name='开始专注 →',exact=True).click()
            expect(page.get_by_role('button',name='暂停专注',exact=True)).to_be_visible()
            page.wait_for_timeout(1300)
            page.reload()
            self.assertEqual(self.db(lambda:FocusSession.objects.filter(owner=self.user).count()),1)
            self.stop_server();self.start_server()
            page.reload()
            expect(page.get_by_role('button',name='暂停专注',exact=True)).to_be_visible()
            self.assertEqual(self.db(lambda:FocusInterval.objects.filter(session__owner=self.user).count()),1)
            self.capture(page,'running-after-server-restart')
            page.get_by_role('button',name='暂停专注',exact=True).click()
            expect(page.get_by_role('button',name='继续专注',exact=True)).to_be_visible()
            session=self.db(lambda:FocusSession.objects.get(owner=self.user))
            paused=self.db(lambda:seconds(session,timezone.now()))
            self.stop_server();self.start_server()
            page.reload()
            expect(page.get_by_role('button',name='继续专注',exact=True)).to_be_visible()
            self.assertEqual(self.db(lambda:seconds(session,timezone.now())),paused)
            self.capture(page,'paused-after-server-restart')
            page.get_by_role('button',name='继续专注',exact=True).click()
            expect(page.get_by_role('button',name='暂停专注',exact=True)).to_be_visible()
            page.wait_for_timeout(1100)
            token=page.locator('#focus-controls [name=csrfmiddlewaretoken]').input_value()
            page.get_by_role('button',name='结束并保存',exact=True).click()
            expect(page.get_by_role('button',name='开始专注 →',exact=True)).to_be_visible()
            self.db(session.refresh_from_db);saved=self.db(lambda:seconds(session,timezone.now()))
            response=context.request.post(base+'/focus/',form={'csrfmiddlewaretoken':token,'action':'finish','session':str(session.pk)})
            self.assertEqual(response.status,200)
            self.db(session.refresh_from_db)
            self.assertEqual(self.db(lambda:seconds(session,timezone.now())),saved)
            self.assertGreaterEqual(saved,2);self.assertLess(saved,25)
            self.assertEqual(session.status,'finished');self.assertEqual(self.db(session.intervals.count),2)
            self.assertEqual(errors,[])
            browser.close()

    def test_rest_multitab_offline_and_simulated_expiry(self):
        from datetime import timedelta
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000})
            page=context.new_page();base=f'http://127.0.0.1:{self.port}'
            page.goto(base+'/focus/')
            page.locator('[name=username]').fill(self.user.username)
            page.locator('[name=password]').fill(self.password)
            page.locator('button[type=submit]').click()
            page.wait_for_url('**/focus/')
            self.capture(page,'focus-with-rest-option')
            page.get_by_role('button',name='休息 5 分钟',exact=True).click()
            expect(page.locator('.focus-start')).to_be_hidden()
            page.reload()
            expect(page.get_by_role('button',name='结束休息，准备学习',exact=True)).to_be_visible()
            self.capture(page,'rest-after-refresh')
            self.assertEqual(self.db(lambda:FocusSession.objects.filter(owner=self.user).count()),0)
            page.get_by_role('button',name='结束休息，准备学习',exact=True).click()
            page.get_by_role('button',name='开始专注 →',exact=True).click()
            expect(page.get_by_role('button',name='暂停专注',exact=True)).to_be_visible()
            tab=context.new_page();tab.goto(base+'/focus/')
            page.get_by_role('button',name='暂停专注',exact=True).click()
            tab.bring_to_front();tab.evaluate("window.dispatchEvent(new Event('online'))")
            expect(tab.get_by_role('button',name='继续专注',exact=True)).to_be_visible(timeout=10000)
            tab.get_by_role('button',name='继续专注',exact=True).click()
            expect(tab.get_by_role('button',name='暂停专注',exact=True)).to_be_visible()
            context.set_offline(True)
            tab.evaluate("window.dispatchEvent(new Event('online'))")
            expect(tab.locator('#timer-message')).to_contain_text('暂时无法同步',timeout=10000)
            self.capture(tab,'offline-message')
            context.set_offline(False)
            tab.evaluate("window.dispatchEvent(new Event('online'))")
            expect(tab.locator('#timer-message')).to_contain_text('计时已同步',timeout=10000)
            session=self.db(lambda:FocusSession.objects.get(owner=self.user))
            self.assertEqual(session.status,'running')
            # Simulate server-side elapsed time; this is not a physical sleep test.
            from django.db.models import F
            shift=timedelta(minutes=26)
            self.db(lambda:FocusSession.objects.filter(pk=session.pk).update(started_at=F('started_at')-shift))
            self.db(lambda:FocusInterval.objects.filter(session=session).update(started_at=F('started_at')-shift,ended_at=F('ended_at')-shift))
            tab.evaluate("window.dispatchEvent(new Event('online'))")
            expect(tab.get_by_role('button',name='开始专注 →',exact=True)).to_be_visible(timeout=10000)
            self.db(session.refresh_from_db)
            self.assertEqual(session.status,'finished')
            self.assertEqual(self.db(lambda:seconds(session,timezone.now())),1500)
            self.assertEqual(self.db(lambda:FocusSession.objects.filter(owner=self.user).count()),1)
            browser.close()

    def test_concurrent_start_and_finish_use_one_session(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connections
        from learning.focus import command
        def operate(action,pk=None):
            try:return command(self.user,action,session_id=pk).pk
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls=[pool.submit(operate,'start') for _ in range(2)]
            ids=[f.result() for f in calls]
            self.assertEqual(ids[0],ids[1])
            calls=[pool.submit(operate,'finish',ids[0]) for _ in range(2)]
            for call in calls:call.result()
        self.assertEqual(FocusSession.objects.filter(owner=self.user).count(),1)
        self.assertEqual(FocusInterval.objects.filter(session__owner=self.user).count(),1)
        self.assertEqual(FocusSession.objects.get(pk=ids[0]).status,'finished')

    def test_course_task_to_focus_and_download(self):
        import json
        from playwright.sync_api import sync_playwright, expect
        task=Task.objects.create(course=self.course,title='关系代数练习',due_date=timezone.localdate())
        out=Path(settings.BASE_DIR).parent/'round4-evidence';out.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
            page=context.new_page();base=f'http://127.0.0.1:{self.port}'
            page.goto(base+f'/courses/{self.course.pk}/')
            page.locator('[name=username]').fill(self.user.username)
            page.locator('[name=password]').fill(self.password)
            page.locator('button[type=submit]').click()
            page.get_by_role('link',name='开始本课程专注 →',exact=True).click()
            expect(page.locator('#focus-course')).to_have_value(str(self.course.pk))
            page.goto(base+'/tasks/')
            page.get_by_role('link',name='专注任务：关系代数练习',exact=True).click()
            expect(page.locator('#focus-course')).to_be_disabled()
            expect(page.locator('[name=task]')).to_have_value(str(task.pk))
            button=page.get_by_role('button',name='开始专注 →',exact=True).bounding_box()
            self.assertLessEqual(button['y']+button['height'],1000)
            page.screenshot(path=str(out/'task-context-before-start.png'),full_page=True)
            page.get_by_role('button',name='开始专注 →',exact=True).click()
            expect(page.get_by_role('button',name='暂停专注',exact=True)).to_be_visible()
            page.screenshot(path=str(out/'task-focus-running.png'),full_page=True)
            session=self.db(lambda:FocusSession.objects.get(owner=self.user))
            self.assertEqual(session.task_id,task.pk)
            page.get_by_role('button',name='结束并保存',exact=True).click()
            expect(page.get_by_role('button',name='开始专注 →',exact=True)).to_be_visible()
            with page.expect_download() as event:
                page.get_by_role('link',name='导出全部专注记录（JSON）',exact=True).click()
            download=event.value
            data=json.loads(Path(download.path()).read_text(encoding='utf-8'))
            self.assertEqual(data['scope'],'focus_only')
            self.assertEqual(data['sessions'][0]['task_title'],task.title)
            self.assertEqual(self.db(lambda:Task.objects.get(pk=task.pk).status),'todo')
            page.screenshot(path=str(out/'task-history-and-export.png'),full_page=True)
            browser.close()

    def test_daily_calendar_pagination_and_real_week_display(self):
        from datetime import timedelta
        from learning.focus import command
        from playwright.sync_api import sync_playwright, expect
        now=timezone.localtime(timezone.now()).replace(hour=10,minute=0,second=0,microsecond=0)-timedelta(days=1)
        for i in range(14):
            start=now+timedelta(minutes=i*2)
            item=command(self.user,'start',course_id=self.course.pk,now=start)
            command(self.user,'finish',item.pk,now=start+timedelta(minutes=1))
        item=command(self.user,'start',now=now+timedelta(hours=1))
        command(self.user,'finish',item.pk,now=now+timedelta(hours=1,minutes=2))
        out=Path(settings.BASE_DIR).parent/'round5-evidence';out.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000})
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            base=f'http://127.0.0.1:{self.port}'
            page.goto(base+'/focus/')
            page.locator('[name=username]').fill(self.user.username)
            page.locator('[name=password]').fill(self.password)
            page.locator('button[type=submit]').click()
            expect(page.locator('#week-total')).to_have_text('16')
            page.screenshot(path=str(out/'synthetic-week-and-history.png'),full_page=True)
            day=now.date().isoformat()
            page.goto(base+'/focus/?day='+day+'#focus-history')
            expect(page.locator('.daily-legend li')).to_have_count(2)
            expect(page.locator('.daily-total strong')).to_have_text('16分00秒')
            expect(page.locator('.focus-history .list-row')).to_have_count(12)
            page.get_by_role('link',name='下一页',exact=True).click()
            expect(page.locator('.focus-history .list-row')).to_have_count(3)
            self.assertIn('day='+day,page.url)
            page.screenshot(path=str(out/'synthetic-history-page2.png'),full_page=True)
            page.locator('.day-picker>summary').focus();page.keyboard.press('Enter')
            expect(page.locator('.day-calendar')).to_be_visible()
            page.get_by_role('link',name='查看前一天',exact=True).click()
            expect(page.locator('.focus-history .list-row')).to_have_count(0)
            expect(page.get_by_text('这一天还没有有效专注记录',exact=True)).to_be_visible()
            page.goto(base+'/focus/?day=invalid#focus-history')
            expect(page.locator('.field-error')).to_contain_text('日期无效')
            expect(page.locator('#week-total')).to_have_text('16')
            self.assertEqual(errors,[])
            browser.close()

    def test_new_user_learning_journey_keyboard_and_narrow_screen(self):
        from learning.models import KnowledgePoint,Chapter,WrongQuestion,ReviewRecord
        from playwright.sync_api import sync_playwright,expect
        self.course.delete()
        out=Path(settings.BASE_DIR).parent/'round6-evidence';out.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000})
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            base=f'http://127.0.0.1:{self.port}'
            page.goto(base+'/')
            page.locator('#main [name=username]').fill(self.user.username)
            page.locator('#main [name=password]').fill(self.password)
            page.locator('button[type=submit]').click()
            expect(page.locator('.focus-card')).to_contain_text('从第一门课程开始')
            page.locator('.skip-link').focus();page.keyboard.press('Enter')
            self.assertEqual(page.evaluate('document.activeElement.id'),'main')
            page.wait_for_timeout(250)
            page.screenshot(path=str(out/'new-user-home.png'),full_page=True)
            page.locator('.focus-card a').focus();page.keyboard.press('Enter')
            page.locator('#main [name=name]').fill('新手数据库课程')
            page.get_by_role('button',name='保存',exact=True).click()
            course_url=page.url
            page.goto(base+'/courses/new/')
            page.locator('#main [name=name]').fill('新手数据库课程')
            page.get_by_role('button',name='保存',exact=True).click()
            expect(page.locator('.has-error')).to_be_visible()
            missing=page.locator('[aria-describedby]').evaluate_all("els=>els.flatMap(e=>e.getAttribute('aria-describedby').split(/\\s+/).filter(id=>!document.getElementById(id)))")
            self.assertEqual(missing,[])
            page.screenshot(path=str(out/'duplicate-course-error.png'),full_page=True)
            page.goto(course_url)
            for title,parent in [('关系模型',None),('关系代数','关系模型')]:
                page.get_by_role('link',name='添加章节',exact=True).click()
                page.locator('#main [name=name]').fill(title)
                if parent:page.locator('#main [name=parent]').select_option(label=parent)
                page.get_by_role('button',name='保存',exact=True).click()
            page.get_by_role('link',name='添加知识点',exact=True).click()
            page.locator('#main [name=name]').fill('投影与选择')
            page.locator('#main [name=chapter]').select_option(label='关系代数')
            page.get_by_role('button',name='保存',exact=True).click()
            page.locator('.chapter-node summary').first.focus();page.keyboard.press('Enter');page.keyboard.press('Enter')
            page.get_by_role('link',name='添加本课程任务',exact=True).click()
            page.locator('#main [name=title]').fill('完成关系代数练习')
            page.locator('#main [name=due_date]').fill(timezone.localdate().isoformat())
            page.get_by_role('button',name='保存',exact=True).click()
            page.get_by_role('link',name='专注任务：完成关系代数练习',exact=True).click()
            page.get_by_role('button',name='开始专注 →',exact=True).click()
            expect(page.get_by_role('button',name='暂停专注',exact=True)).to_be_visible()
            page.get_by_role('button',name='结束并保存',exact=True).click()
            page.goto(course_url)
            page.get_by_role('link',name='记录本课程错题',exact=True).click()
            for name,value in {'title':'区分投影和选择','content':'选择和投影各改变什么？','original_answer':'混淆行列','correct_answer':'选择筛选行，投影选择列。','error_reason':'没有区分运算对象'}.items():page.locator(f'#main [name={name}]').fill(value)
            page.locator('#main [name=knowledge_points]').check()
            page.locator('#main [name=next_review_date]').fill(timezone.localdate().isoformat())
            page.get_by_role('button',name='保存',exact=True).click()
            page.goto(base+'/')
            page.locator('.focus-card a').click()
            expect(page.locator('.reference-answer')).to_have_count(0)
            page.locator('#main [name=answer]').fill('选择筛选行，投影选择列。')
            page.locator('button[data-save]').click()
            expect(page.locator('.reference-answer')).to_be_visible()
            page.locator('#main [name=rating][value=good]').focus();page.keyboard.press('Space')
            page.locator('button[data-save]').click()
            self.assertEqual(self.db(lambda:ReviewRecord.objects.filter(question__course__owner=self.user).count()),1)
            question=self.db(lambda:WrongQuestion.objects.get(course__owner=self.user))
            self.assertGreater(question.next_review_date,timezone.localdate())
            self.assertEqual(self.db(lambda:KnowledgePoint.objects.get(course__owner=self.user).chapter.parent.name),'关系模型')
            page.goto(base+'/tasks/')
            page.locator('.task-complete').focus();page.keyboard.press('Space')
            expect(page.locator('.status-cell')).to_contain_text('已完成')
            self.assertEqual(self.db(lambda:Task.objects.get(course__owner=self.user).status),'done')
            for path,label in [('/', 'home'),(course_url,'course'),('/tasks/','tasks'),('/reviews/','reviews'),('/focus/','focus'),('/statistics/','statistics')]:
                page.set_viewport_size({'width':390,'height':844})
                page.goto(path if path.startswith('http') else base+path)
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth+1'))
                page.screenshot(path=str(out/f'journey-{label}-390.png'),full_page=True)
            page.goto(base+'/focus/')
            page.get_by_role('button',name='休息 5 分钟',exact=True).click()
            page.reload()
            expect(page.get_by_role('button',name='结束休息，准备学习',exact=True)).to_be_visible()
            page.get_by_role('button',name='结束休息，准备学习',exact=True).focus();page.keyboard.press('Enter')
            expect(page.locator('.focus-start')).to_be_visible()
            self.assertEqual(errors,[])
            browser.close()

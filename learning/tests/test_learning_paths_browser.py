import os,unittest
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.test import TransactionTestCase
from django.utils import timezone
from learning.models import Chapter,KnowledgePoint,WrongQuestion,QuestionKnowledgePoint,Task
from . import test_focus_browser as harness

@unittest.skipUnless(os.environ.get('STUDY_RUN_FOCUS_BROWSER')=='1','Opt-in real browser test')
class LearningPathsBrowserTests(TransactionTestCase):
    _fixture_teardown=harness.FocusBrowserTests._fixture_teardown
    setUp=harness.FocusBrowserTests.setUp
    tearDown=harness.FocusBrowserTests.tearDown
    start_server=harness.FocusBrowserTests.start_server
    stop_server=harness.FocusBrowserTests.stop_server
    db=harness.FocusBrowserTests.db

    def test_scoped_skip_restart_last_save_and_cross_chapter_boundary(self):
        from playwright.sync_api import sync_playwright, expect
        chapter=Chapter.objects.create(course=self.course,name='本轮关系模型')
        other=Chapter.objects.create(course=self.course,name='不在本轮的SQL')
        point=KnowledgePoint.objects.create(course=self.course,chapter=chapter,name='范围知识点')
        outside=KnowledgePoint.objects.create(course=self.course,chapter=other,name='其他章节知识点')
        questions=[]
        for index in range(3):
            q=WrongQuestion.objects.create(course=self.course,title=f'范围验收题{index}',content='合成问题',original_answer='原答',correct_answer='参考答案',error_reason='混淆',next_review_date=timezone.localdate())
            QuestionKnowledgePoint.objects.create(question=q,knowledge_point=point if index<2 else outside)
            questions.append(q)
        # Shared across chapters, but only one row in the selected chapter.
        QuestionKnowledgePoint.objects.create(question=questions[0],knowledge_point=outside)
        with sync_playwright() as p:
            b=p.chromium.launch(channel='msedge',headless=True)
            page=b.new_page(viewport={'width':390,'height':844});base=f'http://127.0.0.1:{self.port}'
            page.goto(base+'/');page.locator('[name=username]').fill(self.user.username);page.locator('[name=password]').fill(self.password);page.locator('button[type=submit]').click();page.wait_for_url(base+'/')
            page.goto(base+f'/questions/?chapter={chapter.pk}&review_status=due')
            expect(page.locator('.question-card')).to_have_count(2)
            page.get_by_role('link',name=questions[0].title,exact=True).click()
            self.assertIn(f'chapter={chapter.pk}',page.url)
            page.get_by_role('link',name='开始复习',exact=True).click()
            expect(page.locator('.review-scope')).to_contain_text('本轮关系模型')
            self.assertIn(f'chapter={chapter.pk}',page.url)
            page.get_by_role('button',name='暂时跳过这题',exact=True).click()
            expect(page.locator('h1')).to_have_text(questions[1].title)
            expect(page.locator('.review-scope')).to_contain_text('1 题暂时跳过')
            self.stop_server();self.start_server();page.reload()
            expect(page.locator('.review-scope')).to_contain_text('1 题暂时跳过')
            page.locator('[name=answer]').fill('本轮独立答案');page.get_by_role('button',name='查看答案 →',exact=True).click()
            page.locator('#id_rating_3').check();page.get_by_role('button',name='保存并查看本轮结果 →',exact=True).click()
            expect(page.locator('.empty-state h2')).to_have_text('本轮已浏览，仍有 1 题待复习')
            self.assertIn(f'chapter={chapter.pk}',page.url)
            page.get_by_role('link',name='重新查看跳过题',exact=True).click()
            expect(page.locator('.queue-row')).to_have_count(1)
            page.get_by_role('link',name='开始复习',exact=True).click()
            page.locator('[name=answer]').fill('重新回忆后的答案');page.get_by_role('button',name='查看答案 →',exact=True).click()
            page.locator('#id_rating_3').check();page.get_by_role('button',name='保存并查看本轮结果 →',exact=True).click()
            expect(page.locator('.empty-state h2')).to_have_text('当前范围没有到期错题')
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
            page.get_by_role('link',name='切换到全部课程',exact=True).click()
            expect(page.locator('.queue-row')).to_have_count(1)
            expect(page.locator('.queue-row')).to_contain_text(questions[2].title)
            b.close()

    def test_chapter_review_task_filter_and_fixed_assistant(self):
        from playwright.sync_api import sync_playwright,expect
        chapter=Chapter.objects.create(course=self.course,name='关系模型')
        section=Chapter.objects.create(course=self.course,parent=chapter,name='关系代数')
        point=KnowledgePoint.objects.create(course=self.course,chapter=section,name='选择与投影')
        q=WrongQuestion.objects.create(course=self.course,title='合成章节复习题',content='选择与投影的区别？',original_answer='概念混淆',correct_answer='选择行，投影列。',error_reason='混淆行列',next_review_date=timezone.localdate())
        QuestionKnowledgePoint.objects.create(question=q,knowledge_point=point)
        task=Task.objects.create(course=self.course,title='独立完成关系模型章节的练习并整理自己仍然不理解的概念与对应例子',due_date=timezone.localdate())
        with sync_playwright() as p:
            b=p.chromium.launch(channel='msedge',headless=True);page=b.new_page(viewport={'width':1280,'height':880})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            base=f'http://127.0.0.1:{self.port}'
            page.goto(base+'/');page.locator('[name=username]').fill(self.user.username);page.locator('[name=password]').fill(self.password);page.locator('button[type=submit]').click();page.wait_for_url(base+'/')
            page.goto(base+f'/courses/{self.course.pk}/')
            page.locator('.chapter-learning-links .due-link').first.click()
            expect(page.locator('#chapter')).to_have_value(str(chapter.pk))
            expect(page.locator('.question-card')).to_have_count(1)
            expect(page.locator('.question-scope')).to_contain_text('含下级节')
            page.get_by_role('link',name='开始复习 →',exact=True).click()
            page.locator('[name=answer]').fill('选择满足条件的行，投影选取列。');page.get_by_role('button',name='查看答案 →',exact=True).click()
            page.locator('#id_rating_3').check();page.get_by_role('button',name='保存并查看本轮结果 →',exact=True).click()
            page.wait_for_url('**/reviews/?*')
            page.goto(base+f'/questions/?chapter={chapter.pk}&review_status=due')
            expect(page.locator('.empty-state')).to_contain_text('当前范围没有待复习题目')
            expect(page.locator('#main')).not_to_contain_text('复习已清空')
            page.goto(base+f'/tasks/?course={self.course.pk}&status=todo&q=独立')
            page.get_by_role('button',name='完成',exact=True).click()
            self.assertIn('status=todo',page.url);self.assertIn('course=',page.url)
            expect(page.locator('.task-panel')).to_contain_text('当前范围没有任务')
            page.locator('.task-status-tabs').get_by_role('link',name='已完成 1',exact=True).click()
            expect(page.locator('.task-panel')).to_contain_text(task.title)
            page.get_by_role('button',name='打开学习助手',exact=True).click()
            expect(page.locator('#mi-panel')).to_be_visible()
            page.keyboard.press('Escape');expect(page.locator('#mi-panel')).not_to_be_visible()
            expect(page.get_by_role('button',name='打开学习助手',exact=True)).to_be_focused()
            for width in (1280,768,390):
                page.set_viewport_size({'width':width,'height':880})
                for route in ('/tasks/','/questions/','/statistics/',f'/courses/{self.course.pk}/'):
                    page.goto(base+route)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                    launcher=page.locator('#mi-launcher');expect(launcher).to_be_visible()
                    self.assertEqual(launcher.evaluate('(e)=>getComputedStyle(e).position'),'fixed')
                    initial=launcher.bounding_box()
                    page.evaluate('window.scrollTo(0,document.documentElement.scrollHeight)')
                    expect(launcher).to_be_visible()
                    self.assertAlmostEqual(launcher.bounding_box()['y'],initial['y'],delta=3)
                    self.assertLessEqual(initial['x']+initial['width'],width)
                    self.assertLessEqual(initial['y']+initial['height'],880)
                    if route=='/tasks/' and width==768:
                        self.assertLessEqual(page.locator('.task-table').bounding_box()['width'],page.locator('.task-panel .table-wrap').bounding_box()['width'])
            self.assertEqual(errors,[])
            b.close()

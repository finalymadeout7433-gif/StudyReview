from datetime import datetime,timedelta
from urllib.parse import urlsplit,parse_qs
import uuid
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from learning.models import Course,Chapter,KnowledgePoint,WrongQuestion,QuestionKnowledgePoint,Task,ReviewRecord
from learning.activity import course_activity
from learning.focus import command
from learning.focus_history import course_seconds

class LearningActivityTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('activity-owner')
        self.other=get_user_model().objects.create_user('activity-other')
        self.course=Course.objects.create(owner=self.user,name='数据库')
        self.second=Course.objects.create(owner=self.user,name='算法')
        self.foreign=Course.objects.create(owner=self.other,name='他人课程')
        self.root=Chapter.objects.create(course=self.course,name='关系模型')
        self.section=Chapter.objects.create(course=self.course,name='关系代数',parent=self.root)
        self.other_root=Chapter.objects.create(course=self.second,name='图论')
        self.foreign_root=Chapter.objects.create(course=self.foreign,name='不可访问')
        self.p1=KnowledgePoint.objects.create(course=self.course,chapter=self.section,name='选择')
        self.p2=KnowledgePoint.objects.create(course=self.course,chapter=self.section,name='投影')
        self.today=timezone.localdate()
        self.due=self.question('选择与投影',0,[self.p1,self.p2])
        self.future=self.question('未来安排',2,[self.p1])
        self.archived=self.question('归档旧题',-2,[self.p1],True)
        self.client.force_login(self.user)

    def question(self,title,offset,points,archived=False):
        q=WrongQuestion.objects.create(course=self.course,title=title,content='题目',original_answer='原答',correct_answer='答案',error_reason='错因',next_review_date=self.today+timedelta(days=offset),is_archived=archived)
        for point in points:QuestionKnowledgePoint.objects.create(question=q,knowledge_point=point)
        return q

    def test_chapter_counts_and_filters_deduplicate_shared_question(self):
        r=self.client.get(f'/courses/{self.course.pk}/')
        node=r.context['chapter_tree'][0]
        self.assertEqual(node['question_count'],3)
        self.assertEqual(node['due_count'],1)
        self.assertEqual(node['children'][0]['due_count'],1)
        for chapter in (self.root,self.section):
            response=self.client.get('/questions/',{'chapter':chapter.pk,'review_status':'due'})
            self.assertEqual(response.context['selected_course'],self.course)
            self.assertEqual([q.pk for q in response.context['page_obj']],[self.due.pk])
            self.assertEqual([t['count'] for t in response.context['review_tabs']],[2,1,1])
            self.assertContains(response,'开始复习')
        all_rows=self.client.get('/questions/',{'chapter':self.root.pk,'archive':'all'})
        self.assertEqual(all_rows.context['page_obj'].paginator.count,3)
        self.assertNotContains(self.client.get('/questions/',{'archive':'archived','review_status':'due'}),'开始复习')

    def test_foreign_filters_rejected_and_course_change_clears_stale_selection(self):
        self.assertEqual(self.client.get('/questions/',{'chapter':self.foreign_root.pk}).status_code,404)
        self.assertEqual(self.client.get('/questions/',{'chapter':'-1'}).status_code,404)
        r=self.client.get('/questions/',{'course':self.second.pk,'chapter':self.root.pk,'point':self.p1.pk})
        self.assertEqual(r.status_code,200)
        self.assertIsNone(r.context['selected_chapter']);self.assertIsNone(r.context['selected_point'])
        self.assertTrue(r.context['filter_notice'])
        self.assertEqual(r.context['page_obj'].paginator.count,0)
        self.assertNotContains(r,'不可访问')

    def test_tabs_keep_scope_search_and_remove_pagination(self):
        r=self.client.get('/questions/',{'course':self.course.pk,'chapter':self.root.pk,'q':'选择','page':2})
        for tab in r.context['review_tabs']:
            params=parse_qs(urlsplit(tab['url']).query)
            self.assertEqual(params['q'],['选择']);self.assertEqual(params['chapter'],[str(self.root.pk)])
            self.assertNotIn('page',params)
        self.course.is_archived=True;self.course.save()
        self.assertEqual(self.client.get('/questions/',{'archive':'all','review_status':'due'}).context['page_obj'].paginator.count,0)

    def review(self,question,example=False):
        return ReviewRecord.objects.create(question=question,review_date=self.today,answer='回答',rating='good',next_review_date=self.today+timedelta(days=2),title_snapshot=question.title,question_snapshot='题目',original_answer_snapshot='原答',correct_answer_snapshot='答案',error_reason_snapshot='错因',course_snapshot=self.course.name,submission_key=uuid.uuid4(),is_example=example)

    def test_activity_avoids_join_multiplication_and_honors_review_source(self):
        for i in range(3):Task.objects.create(course=self.course,title=str(i),due_date=self.today,status='done' if i==0 else 'todo',completed_at=timezone.now() if i==0 else None)
        self.review(self.due);self.review(self.future,True)
        start=timezone.now()-timedelta(minutes=12)
        s=command(self.user,'start',course_id=self.course.pk,now=start)
        command(self.user,'pause',s.pk,now=start+timedelta(minutes=2))
        command(self.user,'resume',s.pk,now=start+timedelta(minutes=7))
        command(self.user,'finish',s.pk,now=start+timedelta(minutes=10))
        free=command(self.user,'start',now=start);command(self.user,'finish',free.pk,now=start+timedelta(minutes=5))
        foreign=command(self.other,'start',course_id=self.foreign.pk,now=start);command(self.other,'finish',foreign.pk,now=start+timedelta(minutes=5))
        with self.assertNumQueries(6):rows=course_activity(self.user,None,self.today,self.today,'personal')
        row=next(r for r in rows if r['course'].pk==self.course.pk)
        self.assertEqual((row['tasks_total'],row['tasks_done'],row['questions_total'],row['due'],row['reviews'],row['focus_seconds']),(3,1,2,1,1,300))
        self.assertEqual(row['course'].chapter_count,2);self.assertEqual(row['course'].point_count,2)
        self.assertEqual(course_activity(self.user,self.foreign.pk,self.today,self.today),[])
        self.assertEqual(course_activity(self.user,self.course.pk,self.today,self.today,'all')[0]['reviews'],2)
        self.assertEqual(course_activity(self.user,self.course.pk,self.today,self.today,'example')[0]['reviews'],1)
        self.second.is_archived=True;self.second.save()
        self.assertEqual(len(course_activity(self.user,None,self.today,self.today)),1)

    def test_focus_range_is_actual_cross_midnight_overlap_not_start_date(self):
        start=timezone.make_aware(datetime(2026,11,3,23,50,0,500000))
        s=command(self.user,'start',course_id=self.course.pk,now=start)
        command(self.user,'finish',s.pk,now=start+timedelta(hours=2))
        totals=course_seconds(self.user,[self.course.pk],start.date()+timedelta(days=1),start.date()+timedelta(days=1),now=start+timedelta(days=1))
        self.assertEqual(totals[self.course.pk],900)
        self.assertEqual(course_seconds(self.other,[self.course.pk],start.date(),start.date()+timedelta(days=1)),{})

    def test_task_status_returns_to_filter_and_rejects_external_redirect(self):
        task=Task.objects.create(course=self.course,title='学习任务',due_date=self.today)
        target=f'/tasks/?course={self.course.pk}&status=todo&q=%E5%AD%A6'
        self.assertRedirects(self.client.post(f'/tasks/{task.pk}/status/',{'action':'done','next':target}),target)
        for target in ['https://example.com/tasks/','//example.com/tasks/','/questions/','javascript:alert(1)']:
            self.assertRedirects(self.client.post(f'/tasks/{task.pk}/status/',{'action':'todo','next':target}),'/tasks/')
        response=self.client.get('/tasks/',{'course':self.course.pk})
        self.assertEqual({t['key']:t['count'] for t in response.context['task_tabs']},{'all':1,'todo':1,'today':1,'overdue':0,'done':0})

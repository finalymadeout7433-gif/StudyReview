import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from learning.models import Course, Task, WrongQuestion
from assistant import services
from assistant.models import Draft, Message
from assistant.providers import ProviderResult
from assistant.serializers import draft_data


class ActionWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner=get_user_model().objects.create_user(username='synthetic_rc7_owner')
        cls.other=get_user_model().objects.create_user(username='synthetic_rc7_other')
        cls.course=Course.objects.create(owner=cls.owner,name='合成数学')
        cls.course2=Course.objects.create(owner=cls.owner,name='合成数据库')
        cls.foreign=Course.objects.create(owner=cls.other,name='其他用户课程')
        cls.task=Task.objects.create(course=cls.course,title='复习练习',description='旧笔记',due_date=timezone.localdate())
        cls.same=Task.objects.create(course=cls.course2,title='复习练习',description='另一份笔记',due_date=timezone.localdate())
        cls.foreign_task=Task.objects.create(course=cls.foreign,title='复习练习',due_date=timezone.localdate())
        cls.question=WrongQuestion.objects.create(course=cls.course,title='函数错题',content='旧题干',
            original_answer='旧答案',correct_answer='参考答案',error_reason='旧错因',
            next_review_date=timezone.localdate()+timedelta(days=1))

    def setUp(self):
        self.client.force_login(self.owner)
        self.session,_=services.create_session(self.owner,'合成操作会话',uuid.uuid4())

    def post(self,url,data,client=None):
        return (client or self.client).post(url,json.dumps(data),content_type='application/json')

    def task_draft(self,payload=None):
        selection=services.target_preview(self.owner,'task',self.task.pk)
        return services.create_draft(self.owner,self.session.pk,{'operation':'update_task',
            'target_id':self.task.pk,'expected_version':selection['expected_version'],
            'payload':payload or {'description':'整理后的笔记'},'submission_key':str(uuid.uuid4())})[0]

    def confirm(self,draft,key=None):
        return self.post(reverse('assistant:confirm',args=[draft.pk]),{
            'confirmation_token':services.confirmation_token(draft),'submission_key':str(key or uuid.uuid4())})

    def test_local_name_candidates_disambiguate_courses_without_foreign_records(self):
        result=self.client.get(reverse('assistant:target-choices'),{'kind':'task','query':'复习练习'})
        self.assertEqual(result.status_code,200)
        data=result.json()
        self.assertEqual({row['id'] for row in data['targets']},{self.task.pk,self.same.pk})
        self.assertEqual({row['course_name'] for row in data['targets']},{'合成数学','合成数据库'})
        self.assertFalse(data['provider_called'])
        self.assertNotIn('description',data['targets'][0])

    def test_candidates_exclude_archived_and_require_authentication(self):
        self.course.is_archived=True;self.course.save(update_fields=['is_archived'])
        data=self.client.get(reverse('assistant:target-choices'),{'kind':'task'}).json()
        self.assertEqual([item['id'] for item in data['targets']],[self.same.pk])
        self.assertEqual(Client().get(reverse('assistant:target-choices')).status_code,401)
        self.assertEqual(self.client.get(reverse('assistant:target-choices'),{
            'kind':'task','before':self.foreign_task.pk}).status_code,404)

    def test_notes_natural_request_generates_bound_draft_without_copy_or_write(self):
        calls=[]
        class MockProvider:
            connected=True
            def respond(_self,context):
                calls.append(context)
                return ProviderResult('请确认笔记修改。',({'operation':'update_task','title':'整理任务笔记',
                    'payload':{'description':'第一步：复习定义\n第二步：练习两题'}},))
        selected=services.target_preview(self.owner,'task',self.task.pk)
        body={'text':'帮我把这个任务说明整理成两步','submission_key':str(uuid.uuid4()),
              'selected_target':{'kind':'task','id':self.task.pk,'expected_version':selected['expected_version'],
                                 'field_scope':['description']}}
        with patch('assistant.services.get_provider',return_value=MockProvider()):
            response=self.post(reverse('assistant:messages',args=[self.session.pk]),body)
            replay=self.post(reverse('assistant:messages',args=[self.session.pk]),body)
        self.assertEqual(response.status_code,201);self.assertEqual(replay.status_code,200)
        self.assertEqual(len(calls),1)
        draft=response.json()['drafts'][0]
        self.assertEqual(draft['before']['description'],'旧笔记')
        self.assertIn('第一步',draft['after']['description'])
        self.task.refresh_from_db();self.assertEqual(self.task.description,'旧笔记')
        self.assertEqual(calls[0].selected_target_snapshot['allowed_fields'],['description'])
        self.assertEqual(calls[0].selected_target_snapshot['local_date'],timezone.localdate().isoformat())
        applied=self.confirm(Draft.objects.get(pk=draft['id']))
        self.assertEqual(applied.status_code,200)
        self.task.refresh_from_db();self.assertIn('第二步',self.task.description)
        self.assertEqual(self.task.title,'复习练习')
        self.same.refresh_from_db();self.assertEqual(self.same.description,'另一份笔记')

    def test_model_cannot_expand_notes_scope(self):
        class MockProvider:
            connected=True
            def respond(_self,context):
                return ProviderResult('不合规建议',({'operation':'update_task',
                    'payload':{'description':'新笔记','title':'不允许的标题'}},))
        selected=services.target_preview(self.owner,'task',self.task.pk)
        with patch('assistant.services.get_provider',return_value=MockProvider()):
            response=self.post(reverse('assistant:messages',args=[self.session.pk]),{
                'text':'整理笔记','submission_key':str(uuid.uuid4()),
                'selected_target':{'kind':'task','id':self.task.pk,
                    'expected_version':selected['expected_version'],'field_scope':['description']}})
        self.assertEqual(response.status_code,201);self.assertEqual(response.json()['drafts'],[])
        self.assertEqual(response.json()['response']['status'],Message.Status.PROVIDER_ERROR)
        self.task.refresh_from_db();self.assertEqual(self.task.description,'旧笔记')

    def test_done_and_reopen_status_are_atomic_and_persist_after_page_read(self):
        draft=self.task_draft({'title':'已整理任务','status':'done'})
        self.assertEqual(draft.after_snapshot['completed_at'],'确认保存时记录完成时间')
        key=uuid.uuid4();first=self.confirm(draft,key);second=self.confirm(draft,key)
        self.assertTrue(first.json()['applied']);self.assertTrue(second.json()['replayed'])
        self.task.refresh_from_db();self.assertEqual(self.task.status,'done');self.assertIsNotNone(self.task.completed_at)
        html=self.client.get(reverse('task-list')).content.decode()
        self.assertIn('已整理任务',html)
        undo=self.task_draft({'status':'todo'});self.assertEqual(self.confirm(undo).status_code,200)
        self.task.refresh_from_db();self.assertEqual(self.task.status,'todo');self.assertIsNone(self.task.completed_at)

    def test_cancel_is_idempotent_preserves_snapshots_and_rejects_old_confirmation(self):
        draft=self.task_draft();before=dict(draft.before_snapshot);after=dict(draft.after_snapshot)
        for _ in range(2):
            response=self.post(reverse('assistant:cancel',args=[draft.pk]),{})
            self.assertEqual(response.status_code,200);self.assertTrue(response.json()['draft']['cancelled'])
        draft.refresh_from_db()
        self.assertEqual(draft.before_snapshot,before);self.assertEqual(draft.after_snapshot,after)
        self.assertEqual(self.confirm(draft).status_code,409)
        self.task.refresh_from_db();self.assertEqual(self.task.description,'旧笔记')
        saved=self.task_draft();self.assertEqual(self.confirm(saved).status_code,200)
        self.assertEqual(self.post(reverse('assistant:cancel',args=[saved.pk]),{}).status_code,409)

    def test_cancel_owner_and_csrf(self):
        draft=self.task_draft()
        other=Client();other.force_login(self.other)
        self.assertEqual(self.post(reverse('assistant:cancel',args=[draft.pk]),{},other).status_code,404)
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.owner)
        self.assertEqual(self.post(reverse('assistant:cancel',args=[draft.pk]),{},strict).status_code,403)
        draft.refresh_from_db();self.assertFalse(draft_data(draft)['cancelled'])

    def test_concurrent_manual_edit_refuses_stale_draft(self):
        draft=self.task_draft()
        Task.objects.filter(pk=self.task.pk).update(description='其他窗口刚保存的笔记')
        self.assertEqual(self.confirm(draft).status_code,409)
        self.task.refresh_from_db();self.assertEqual(self.task.description,'其他窗口刚保存的笔记')
        draft.refresh_from_db();self.assertEqual(draft.status,'pending')

    def test_status_failure_rolls_back_task_fields_and_draft(self):
        draft=self.task_draft({'title':'不能部分写入','status':'done'})
        with patch('learning.services.set_task_status',side_effect=ValidationError('合成故障')):
            self.assertEqual(self.confirm(draft).status_code,400)
        self.task.refresh_from_db();self.assertEqual(self.task.title,'复习练习');self.assertEqual(self.task.status,'todo')
        draft.refresh_from_db();self.assertEqual(draft.status,'pending')

    def test_question_edit_uses_same_preview_confirmation_and_history_boundary(self):
        selected=services.target_preview(self.owner,'question',self.question.pk)
        draft,_=services.create_draft(self.owner,self.session.pk,{'operation':'update_question',
            'target_id':self.question.pk,'expected_version':selected['expected_version'],
            'payload':{'content':'新题干','error_reason':'符号看错'},'submission_key':str(uuid.uuid4())})
        self.question.refresh_from_db();self.assertEqual(self.question.content,'旧题干')
        self.assertEqual(self.confirm(draft).status_code,200)
        self.question.refresh_from_db();self.assertEqual(self.question.content,'新题干')
        self.assertEqual(self.question.correct_answer,'参考答案')

    def test_invalid_status_and_scope_are_rejected(self):
        with self.assertRaises(ValidationError):self.task_draft({'status':'delete'})
        selected=services.target_preview(self.owner,'task',self.task.pk)
        with self.assertRaises(ValidationError):
            services._selected_scope(self.owner,{'kind':'task','id':self.task.pk,
                'expected_version':selected['expected_version'],'field_scope':['owner']},None)

    def test_provider_contract_is_explicit_and_signing_token_stays_local(self):
        from assistant.deepseek_provider import ProviderRequest,prepare_request
        selection=services.target_preview(self.owner,'task',self.task.pk)
        snapshot={'kind':'task','id':self.task.pk,'fields':selection['snapshot'],
                  'allowed_fields':['description'],'local_date':timezone.localdate().isoformat()}
        prepared=prepare_request(ProviderRequest(uuid.uuid4(),'Synthetic instructions',
            ({'role':'user','text':'整理笔记'},),selected_target_snapshot=snapshot))
        body=json.loads(prepared.payload)
        self.assertIn('update_task',body['messages'][0]['content'])
        self.assertIn('changed fields only',body['messages'][0]['content'])
        self.assertIn('allowed_fields',body['messages'][-1]['content'])
        self.assertNotIn(selection['expected_version'],prepared.payload.decode())

"""Actual native WebView2 + isolated MySQL action flow, synthetic provider only."""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parent.parent
TASK=ROOT.parent
state=json.loads((TASK/'v2-rc7-isolated-environment.json').read_text(encoding='utf-8'))
os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']='--disable-gpu'
os.environ['STUDY_DEBUG']='0'
sys.path.insert(0,str(ROOT))
from desktop.runtime import RuntimePaths,InstanceLock,OwnedServer,wait_for_health
from desktop.main import build_wsgi
from desktop.webview_window import open_window
from desktop.native_probe_tools import NativeProbeTools,wait_until
paths=RuntimePaths.resolve(str(ROOT),state['data'],None)
paths.apply_environment('config.v2_development_settings')
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connections,close_old_connections
from django.utils import timezone
from learning.models import Course,Task,WrongQuestion
from assistant import services
from assistant.models import Draft,Message
from assistant.providers import ProviderResult

nonce=uuid.uuid4().hex[:8]
username='synthetic_rc7_native_'+nonce
password='SyntheticLocalOnly2026!'
owner=get_user_model().objects.create_user(username=username,password=password)
course=Course.objects.create(owner=owner,name='合成数学 '+nonce)
other_course=Course.objects.create(owner=owner,name='合成数据库 '+nonce)
task=Task.objects.create(course=course,title='同名合成练习',description='原始任务笔记',due_date=timezone.localdate())
same=Task.objects.create(course=other_course,title='同名合成练习',description='另一课程笔记',due_date=timezone.localdate())
question=WrongQuestion.objects.create(course=course,title='合成函数错题',content='合成题干',original_answer='合成作答',
    correct_answer='合成参考答案',error_reason='原始错因',next_review_date=timezone.localdate()+dt.timedelta(days=1))
OUT=ROOT/'desktop/evidence'/('rc7-native-actions-'+nonce+'.json')
report={'status':'running','checks':[],'real_ai_called':False,'api_key_read_or_configured':False,
        'database':state['database'],'data':state['data'],'account_kind':'synthetic-only','captures':[],
        'simulated_provider_calls':0}
def save():
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
def check(name,value):
    report['checks'].append({'name':name,'passed':bool(value)});save()
    if not value:raise RuntimeError('Check failed: '+name)
class SyntheticProvider:
    connected=True
    def respond(self,context):
        report['simulated_provider_calls']+=1
        selected=context.selected_target_snapshot
        fields=selected.get('allowed_fields') if selected else None
        text=context.messages[-1]['text']
        if not selected:return ProviderResult('请选择明确对象。',())
        if selected['kind']=='question':
            return ProviderResult('错因修改待确认。',({'operation':'update_question','title':'修改错因',
                'payload':{'error_reason':'核对负号，再检查代入顺序'}},))
        if fields==['description']:
            return ProviderResult('笔记修改待确认。',({'operation':'update_task','title':'整理任务笔记',
                'payload':{'description':'整理后的简洁笔记'}},))
        return ProviderResult('任务修改待确认。',({'operation':'update_task','title':'任务延期与步骤',
            'payload':{'description':'第一步：复习定义\n第二步：练习两题',
                       'due_date':(timezone.localdate()+dt.timedelta(days=1)).isoformat()}},))
provider=SyntheticProvider()
original_factory=services.get_provider
services.get_provider=lambda user,key:provider
app=build_wsgi()
def application(environ,start_response):
    # Test-only WSGI wrapper; no production route/setting can select this provider.
    if environ.get('PATH_INFO')=='/ai/config/' and environ.get('REQUEST_METHOD')=='GET':
        body=json.dumps({'enabled':True,'configured':False,'label':'合成 provider 验收 · 不联网',
                         'budget_cny':'0','spent_cny':'0','reserved_cny':'0','remaining_cny':'0'}).encode()
        start_response('200 OK',[('Content-Type','application/json'),('Content-Length',str(len(body)))])
        return [body]
    return app(environ,start_response)
server=None;lock=None;finished=threading.Event()
def probe(window,guard):
    tools=NativeProbeTools(window)
    def execute(script):return tools.execute(script)
    def ready(name,script,seconds=10):
        def condition():
            try:return execute(script)
            except Exception:return False
        check(name,wait_until(condition,seconds))
    def capture(label):
        entry=tools.capture_png(OUT.with_name(OUT.stem+'-'+label+'.png'))
        report['captures'].append(entry);save()
    def send(text):
        execute("document.getElementById('mi-text').value="+json.dumps(text)+";document.getElementById('mi-composer').requestSubmit();")
    try:
        check('native_guard_installed',guard.installed.is_set())
        ready('actual_login_document',"location.pathname==='/accounts/login/'&&document.readyState==='complete'")
        execute("document.querySelector('[name=username]').value="+json.dumps(username)+
                ";document.querySelector('[name=password]').value="+json.dumps(password)+
                ";document.querySelector('[name=password]').form.requestSubmit();")
        ready('actual_authenticated_dashboard',"location.pathname==='/'&&document.readyState==='complete'")
        execute("location.href='/tasks/';")
        ready('actual_task_page',"location.pathname==='/tasks/'&&!!document.getElementById('mi-launcher')")
        execute("document.getElementById('mi-launcher').click();")
        ready('assistant_session_loaded',"document.getElementById('mi-session').options.length>0&&document.getElementById('mi-provider-state').textContent.includes('合成')")
        session_a=execute("document.getElementById('mi-session').value")
        execute("document.getElementById('mi-action').value='task';document.getElementById('mi-action').dispatchEvent(new Event('change'));")
        send('把同名合成练习推迟到明天，任务说明整理成两步')
        ready('ambiguous_request_shows_local_candidates_preserves_input',
              "document.querySelectorAll('[data-candidate-id]').length===2&&document.getElementById('mi-text').value.includes('推迟')")
        check('no_provider_before_explicit_object_choice',report['simulated_provider_calls']==0)
        check('same_name_candidates_show_distinct_courses',execute(
            "document.getElementById('mi-target-candidates').textContent.includes('合成数学')&&document.getElementById('mi-target-candidates').textContent.includes('合成数据库')"))
        execute("document.getElementById('mi-target-query').value='同名合成';document.getElementById('mi-search-target').click();")
        ready('name_search_has_two_candidates',"document.querySelectorAll('[data-candidate-id]').length===2")
        execute("document.querySelector('[data-candidate-id=\""+str(task.pk)+"\"]').click();")
        ready('chosen_target_identity_visible',"document.getElementById('mi-target-preview').textContent.includes('任务 #"+str(task.pk)+"')")
        execute("document.getElementById('mi-composer').requestSubmit();document.getElementById('mi-composer').requestSubmit();")
        ready('natural_request_generated_one_structured_draft',"document.querySelectorAll('[data-draft-confirm]').length===1")
        check('double_send_single_mock_call',report['simulated_provider_calls']==1)
        close_old_connections();task.refresh_from_db()
        check('preview_has_not_written_task',task.description=='原始任务笔记' and task.due_date==timezone.localdate())
        check('changed_fields_show_old_and_new',execute(
            "document.querySelector('.mi-change-table').textContent.includes('原始任务笔记')&&document.querySelector('.mi-change-table').textContent.includes('第二步')"))
        check('all_three_change_columns_fit_visible_panel',execute(
            "document.querySelector('.mi-change-table').getBoundingClientRect().right<=document.getElementById('mi-panel').getBoundingClientRect().right-8"))
        capture('01-task-preview')
        execute("document.getElementById('mi-new-session').click();")
        ready('second_session_created',"document.getElementById('mi-session').value!=="+json.dumps(session_a))
        session_b=execute("document.getElementById('mi-session').value")
        execute("document.getElementById('mi-text').value='B 会话独立输入';document.getElementById('mi-session').value="+json.dumps(session_a)+";document.getElementById('mi-session').dispatchEvent(new Event('change'));")
        ready('switch_back_restores_session_a_draft',"document.querySelectorAll('[data-draft-confirm]').length===1&&document.getElementById('mi-session').value==="+json.dumps(session_a))
        execute("document.getElementById('mi-session').value="+json.dumps(session_b)+";document.getElementById('mi-session').dispatchEvent(new Event('change'));")
        ready('session_b_composer_is_separate',"document.getElementById('mi-text').value==='B 会话独立输入'&&document.querySelectorAll('[data-draft-confirm]').length===0")
        execute("document.getElementById('mi-session').value="+json.dumps(session_a)+";document.getElementById('mi-session').dispatchEvent(new Event('change'));")
        ready('return_to_session_a',"document.querySelectorAll('[data-draft-confirm]').length===1")
        execute("document.getElementById('mi-text').value='确认后继续的问题';const button=document.querySelector('[data-draft-confirm]');button.click();button.click();document.getElementById('mi-session').value="+json.dumps(session_b)+";document.getElementById('mi-session').dispatchEvent(new Event('change'));")
        ready('confirm_reloads_page_and_restores_original_session',
              "document.readyState==='complete'&&document.getElementById('mi-session').value==="+json.dumps(session_a)+"&&document.getElementById('mi-draft-list').textContent.includes('已确认保存')",15)
        ready('unsent_text_survives_confirmation_refresh',"document.getElementById('mi-text').value==='确认后继续的问题'")
        close_old_connections();task.refresh_from_db();same.refresh_from_db()
        check('database_task_changed_once_and_other_same_name_preserved',
              task.description.startswith('第一步') and task.due_date==timezone.localdate()+dt.timedelta(days=1)
              and same.description=='另一课程笔记' and Draft.objects.filter(session_id=session_a,status='applied').count()==1)
        check('refreshed_main_page_contains_saved_fields',execute(
            "document.querySelector('#main table').textContent.includes('第一步')"))
        capture('02-task-saved')
        execute("document.querySelector('[data-mi-action=\"task_note\"][data-mi-target-id=\""+str(task.pk)+"\"]').click();")
        ready('notes_current_object_entry_selected',"document.getElementById('mi-action').value==='task_note'&&document.getElementById('mi-target-preview').textContent.includes('任务 #"+str(task.pk)+"')")
        send('把说明改成简洁笔记')
        ready('notes_only_draft_generated',"document.querySelectorAll('[data-draft-confirm]').length===1")
        check('note_preview_changes_only_description',execute(
            "Array.from(document.querySelectorAll('[data-draft-confirm]')).every(button=>{const rows=button.closest('article').querySelectorAll('[data-changed-field]');return rows.length===1&&rows[0].dataset.changedField==='description';})"))
        execute("const button=document.querySelector('[data-draft-cancel]');button.click();button.click();")
        ready('double_cancel_persists_cancelled_state',"document.getElementById('mi-draft-list').textContent.includes('已取消')&&document.querySelectorAll('[data-draft-confirm]').length===0")
        close_old_connections();task.refresh_from_db()
        check('cancel_preserves_current_task',task.description.startswith('第一步'))
        send('再整理一次说明')
        ready('new_note_draft_for_conflict',"document.querySelectorAll('[data-draft-confirm]').length===1")
        close_old_connections();Task.objects.filter(pk=task.pk).update(description='另一个窗口合法保存的笔记')
        execute("document.querySelector('[data-draft-confirm]').click();")
        ready('stale_concurrent_edit_refused',"document.getElementById('mi-feedback').textContent.includes('变化')")
        close_old_connections();task.refresh_from_db()
        check('concurrent_edit_retained_without_overwrite',task.description=='另一个窗口合法保存的笔记')
        capture('03-version-conflict')
        execute("document.querySelector('[data-draft-cancel]').click();")
        ready('conflicting_draft_can_cancel',"document.querySelectorAll('[data-draft-confirm]').length===0")
        execute("location.href='/questions/"+str(question.pk)+"/';")
        ready('actual_question_detail',"location.pathname==='/questions/"+str(question.pk)+"/'&&!!document.querySelector('[data-mi-target=question]')")
        execute("document.querySelector('[data-mi-target=question]').click();")
        ready('current_question_object_selected',"document.getElementById('mi-target-preview').textContent.includes('错题 #"+str(question.pk)+"')")
        send('更新这个错题的错因')
        ready('question_natural_draft',"document.querySelectorAll('[data-draft-confirm]').length===1")
        close_old_connections();question.refresh_from_db();check('question_preview_not_applied',question.error_reason=='原始错因')
        capture('04-question-preview')
        execute("document.querySelector('[data-draft-confirm]').click();")
        ready('question_confirmation_refresh_persistent',"document.readyState==='complete'&&document.querySelector('#main').textContent.includes('核对负号')",15)
        close_old_connections();question.refresh_from_db()
        check('question_changed_expected_field_only',question.error_reason.startswith('核对负号') and question.correct_answer=='合成参考答案')
        report['status']='passed'
    except Exception as error:
        report['status']='failed';report['error_type']=type(error).__name__
        if isinstance(error,RuntimeError):report['failed_check']=str(error)
        try:capture('failure')
        except Exception:pass
    finally:
        connections.close_all();save();finished.set();tools.invoke(window.native.Close)

try:
    lock=InstanceLock(paths.lock).acquire()
    server=OwnedServer(application).start()
    check('isolated_mysql_health',wait_for_health(server.base_url,stopped=server.failed)['db'] is True)
    server.write_state(paths.state)
    profile=paths.private/('rc7-native-profile-'+nonce)
    profile.mkdir(exist_ok=False)
    open_window(server,profile,smoke_seconds=180,on_ready=probe)
    finished.wait(3)
    if report['status']=='running':report['status']='failed';report['failed_check']='probe did not complete'
finally:
    services.get_provider=original_factory
    if server:
        server.close();server.remove_state(paths.state)
        check('owned_server_clean_exit',not server.thread.is_alive())
    if lock:lock.release()
    save()
(TASK/'v2-rc7-native-pointer.json').write_text(json.dumps({'report':str(OUT),'status':report['status']},indent=2),encoding='utf-8')
print(json.dumps({'status':report['status'],'checks':len(report['checks']),'report':str(OUT),
                  'simulated_provider_calls':report['simulated_provider_calls'],'real_ai_called':False}))
raise SystemExit(0 if report['status']=='passed' else 1)

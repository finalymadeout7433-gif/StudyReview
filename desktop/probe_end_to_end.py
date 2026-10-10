"""Real native UI on the isolated synthetic DB; no model fixtures in product UI."""
import argparse,base64,io,json,socket,threading,uuid
from datetime import datetime,timezone
from pathlib import Path
from desktop.main import build_wsgi
from desktop.runtime import RuntimePaths,InstanceLock,OwnedServer,wait_for_health,DesktopError
from desktop.setup_wizard import run_wizard
from desktop.webview_window import open_window
from desktop.native_probe_tools import NativeProbeTools,wait_until

PASSWORD='SyntheticFlow2026!'
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--resume');args=parser.parse_args();output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    previous=json.loads(Path(args.resume).read_text(encoding='utf-8'))if args.resume else None
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    username=previous['username']if previous else'synthetic_flow_'+stamp.lower()
    resources=Path(__file__).resolve().parent.parent
    report={'status':'running','checks':[],'screenshots':[],'username':username,'synthetic_only':True,'real_ai_called':False,
        'AI_path':'not connected; human entered known synthetic answer in manual draft',
        'started_utc':datetime.now(timezone.utc).isoformat(),'stage':'reopen'if previous else'create'}
    server=paths=lock=None;finished=threading.Event()
    def check(name,value):
        report['checks'].append({'name':name,'passed':bool(value)});print(name,bool(value),flush=True)
        if not value:raise DesktopError('端到端验证失败：'+name)
    def ready_wizard(form,controls):
        from System.Windows.Forms import Timer
        check('wizard_does_not_precheck_save',not controls['confirm'].Checked and not controls['replace'].Checked)
        timer=Timer();timer.Interval=200;count={'n':0};report['_wizard_timer']=timer
        def tick(sender,event):
            count['n']+=1
            if controls['launch'].Enabled:
                timer.Stop();check('wizard_readonly_check_ready',True);controls['launch'].PerformClick();timer.Dispose()
            elif count['n']>=60:timer.Stop();form.Close();timer.Dispose()
        timer.Tick+=tick;timer.Start();controls['check'].PerformClick()
    def probe(window,guard):
        tools=NativeProbeTools(window)
        execute=tools.execute
        tools.execute=lambda script:execute(script,seconds=10)
        def wait(name,condition,seconds=12):check(name,wait_until(lambda:tools.execute(condition),seconds=seconds))
        def navigate(path):
            tools.execute('location.href='+json.dumps(server.base_url+path))
            wait('navigate '+path,'location.pathname==='+json.dumps(path)+'&&document.readyState==="complete"')
        def fill(form_selector,values):
            tools.execute('(()=>{const f=document.querySelector('+json.dumps(form_selector)+');for(const[k,v]of Object.entries('+json.dumps(values,ensure_ascii=False)+')){f.elements[k].value=v;f.elements[k].dispatchEvent(new Event("input",{bubbles:true}));f.elements[k].dispatchEvent(new Event("change",{bubbles:true}));}return true;})()')
        def submit(selector='form.stack-form'):
            tools.execute('setTimeout(()=>document.querySelector('+json.dumps(selector)+').requestSubmit(),30);true')
        def capture(name):
            target=output.with_name(output.stem+'-'+name+'.png');report['screenshots'].append(tools.capture_png(target))
        try:
            wait('native_login_ready','location.pathname==="/accounts/login/"&&document.readyState==="complete"')
            capture('01-login')
            if not previous:
                navigate('/accounts/register/');fill('form.stack-form',{'username':username,'password1':PASSWORD,'password2':PASSWORD});submit()
                wait('new_user_registered_in_native_window','location.pathname==="/courses/new/"&&document.body.textContent.includes("注册成功")')
                navigate('/courses/new/');fill('form.stack-form',{'name':'合成演示·加法与复习','description':'端到端验证自产数据，不是真实学生材料。'});submit()
                wait('new_course_saved','/^\\/courses\\/\\d+\\/$/.test(location.pathname)&&document.readyState==="complete"')
                report['course_id']=tools.execute('Number(location.pathname.split("/")[2])')
                navigate('/courses/'+str(report['course_id'])+'/points/new/');fill('form.stack-form',{'name':'基本加法'});submit()
                wait('knowledge_point_saved','location.pathname==="/courses/'+str(report['course_id'])+'/"&&document.body.textContent.includes("基本加法")')
            else:
                fill('form.stack-form',{'username':username,'password':PASSWORD});submit()
                wait('reopened_user_login','location.pathname==="/"&&!!document.querySelector(".dashboard-heading")')
                report['course_id']=previous['course_id'];report['question_id']=previous['question_id']
            tools.execute('document.getElementById("mi-launcher").click();true')
            wait('native_chat_loaded','!!document.querySelector("#mi-session option")&&document.getElementById("mi-send").textContent==="保存问题"')
            wait('honest_unconnected_notice','!document.getElementById("mi-offline-note").hidden&&document.getElementById("mi-offline-note").textContent.includes("只在本机保存")')
            if previous:
                wait('chat_text_and_image_persist_after_process_restart','document.getElementById("mi-message-log").textContent.includes("合成课堂图片问题")&&!!document.querySelector("#mi-message-log .image-gallery img")')
                check('applied_draft_persisted',tools.execute('document.getElementById("mi-draft-list").textContent.includes("已确认保存")'))
                tools.execute('document.getElementById("mi-panel").close();true')
                navigate('/questions/'+str(report['question_id'])+'/')
                wait('review_history_persists_after_restart','document.querySelectorAll(".history-card").length===1&&document.body.textContent.includes("FSRS")')
                check('original_image_still_authorized',tools.execute('!!document.querySelector(".image-gallery img")'))
                capture('06-reopened-history')
            else:
                from PIL import Image,ImageDraw,ImageFont
                image=Image.new('RGB',(880,280),'#faf5eb');draw=ImageDraw.Draw(image)
                font=ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc',30)
                draw.text((30,35),'合成课堂题图：2 + 3 = ?',font=font,fill='#202020')
                draw.text((30,110),'仅用于上传、保存、复习验证。答案由人手动填写。',font=font,fill='#202020')
                blob=io.BytesIO();image.save(blob,format='PNG');encoded=base64.b64encode(blob.getvalue()).decode()
                def add_image(kind):
                    source='''(()=>{const bytes=Uint8Array.from(atob(ENCODED),c=>c.charCodeAt(0));const file=new File([bytes],'合成课堂加法.png',{type:'image/png'});const transfer=new DataTransfer();transfer.items.add(file);
const event=KIND==='paste'?new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:transfer}):new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer});
document.querySelector(KIND==='paste'?'#mi-composer':'[data-image-editor=chat] [data-image-drop]').dispatchEvent(event);return true;})()'''
                    tools.execute(source.replace('ENCODED',json.dumps(encoded)).replace('KIND',json.dumps(kind)))
                    wait('actual DOM '+kind+' uploads image','(()=>{const e=document.querySelector("[data-image-editor=chat]").imageEditor;return e.pending===0&&e.items.length===1})()')
                add_image('paste');tools.execute('document.getElementById("mi-text").value="合成课堂图片问题：请保存在本机，接下来由人手动整理答案。";document.getElementById("mi-composer").requestSubmit();true')
                wait('local_chat_saved_with_system_record','!document.getElementById("mi-send").disabled&&document.getElementById("mi-message-log").textContent.includes("合成课堂图片问题")&&document.getElementById("mi-message-log").textContent.includes("系统记录")')
                check('no_fake_AI_answer',tools.execute('!document.querySelector(".mi-message[data-role=assistant]")'))
                capture('02-chat-image');add_image('drop')
                tools.execute('document.querySelector("[data-mi-pane=drafts]").click();document.querySelector(".mi-draft-editor").open=true;true')
                from django.utils import timezone as django_timezone
                fill('#mi-draft-form',{'course_id':str(report['course_id']),'title':'合成课堂加法错题','content':'2 + 3 = ?（合成演示，人工整理）','original_answer':'误写成4','correct_answer':'5（人工输入，没有AI识别）','error_reason':'加法计数疏漏','next_review_date':django_timezone.localdate().isoformat()})
                tools.execute('document.getElementById("mi-draft-include-images").checked=true;const p=document.getElementById("mi-draft-points");if(p.options.length)p.options[0].selected=true;document.getElementById("mi-draft-form").requestSubmit();true')
                wait('draft_preview_with_owned_image','!!document.querySelector(".mi-draft-card .image-gallery img")&&document.getElementById("mi-draft-list").textContent.includes("5（人工输入")')
                check('draft_schema_fields_and_booleans_are_Chinese',tools.execute('document.getElementById("mi-draft-list").textContent.includes("课程已归档：否")&&!document.getElementById("mi-draft-list").textContent.includes("course_archived")'))
                tools.execute('document.querySelector(".mi-draft-editor").open=false;document.querySelector(".mi-draft-card").scrollIntoView();true');capture('03-draft-preview')
                tools.execute('document.querySelector(".mi-draft-card [data-image-open]").click();true')
                wait('draft_original_image_authorized','document.getElementById("learning-image-full").complete&&document.getElementById("learning-image-full").naturalWidth===880')
                tools.execute('document.getElementById("learning-image-viewer").close();document.querySelector(".mi-draft-card .button.primary").click();true')
                wait('human_confirm_applies_question_once','document.getElementById("mi-draft-list").textContent.includes("已确认保存")&&!!document.querySelector(".mi-draft-card a.back-link")')
                report['question_id']=tools.execute('Number(document.querySelector(".mi-draft-card a.back-link").getAttribute("href").split("/")[2])')
                tools.execute('document.getElementById("mi-panel").close();true');navigate('/questions/'+str(report['question_id'])+'/')
                wait('question_image_and_answer_saved','document.body.textContent.includes("人工输入，没有AI识别")&&!!document.querySelector(".image-gallery img")')
                navigate('/reviews/'+str(report['question_id'])+'/');fill('form.stack-form',{'answer':'本次合成作答：2 + 3 = 5'});submit()
                wait('answer_reveal_and_FSRS_proposals','!!document.querySelector(".reference-answer")&&!!document.querySelector(".schedule-preview-explanation")')
                tools.execute('const r=document.querySelector("input[name=rating][value=hard]");r.checked=true;r.dispatchEvent(new Event("change",{bubbles:true}));document.querySelector("[name=next_review_date]").value="";document.querySelector("[name=note]").value="合成复习，使用FSRS建议。";true')
                check('FSRS_visible_before_review_save',tools.execute('document.querySelector("[data-schedule-preview]").textContent.includes("FSRS建议复习日期")'));capture('04-FSRS-plan');submit()
                wait('review_transaction_completed','location.pathname!=="/reviews/'+str(report['question_id'])+'/"&&document.readyState==="complete"')
                navigate('/questions/'+str(report['question_id'])+'/')
                wait('immutable_review_history_has_one_snapshot','document.querySelectorAll(".history-card").length===1&&document.body.textContent.includes("本次合成作答")')
                tools.execute('document.querySelector("details.snapshot").open=true;true');capture('05-review-history')
            report['status']='passed'
        except Exception as error:
            report['status']='failed';report['error']=str(error)if isinstance(error,DesktopError)else type(error).__name__
            try:capture('failure')
            except Exception:pass
        finally:finished.set();window.destroy()
    try:
        choice=run_wizard(resources,args.data_dir,settings_module='config.v2_development_settings',on_shown=ready_wizard)
        report.pop('_wizard_timer',None);check('wizard_explicit_open_selection',bool(choice))
        paths=RuntimePaths.resolve(resources,choice['data_dir'],choice['credentials_file']);paths.apply_environment('config.v2_development_settings')
        lock=InstanceLock(paths.lock).acquire();server=OwnedServer(build_wsgi()).start();wait_for_health(server.base_url,stopped=server.failed);server.write_state(paths.state)
        from django.conf import settings
        check('exact_synthetic_database_only',settings.DATABASES['default']['NAME'].startswith('study_review_v2_dev_'))
        profile=paths.private/('flow-profile-'+uuid.uuid4().hex);profile.mkdir()
        open_window(server,profile,smoke_seconds=150,on_ready=probe);finished.wait(5)
        if report['status']=='passed':
            from django.contrib.auth import get_user_model
            from learning.models import WrongQuestion,ReviewRecord
            from scheduling.models import SchedulingState,ScheduleEvent
            from assistant.models import Message,Draft
            owner=get_user_model().objects.get(username=username);question=WrongQuestion.objects.get(pk=report['question_id'],course__owner=owner)
            from django.utils import timezone as django_timezone
            check('backend_one_review_one_state_one_event',ReviewRecord.objects.filter(question=question).count()==1 and SchedulingState.objects.filter(question=question).count()==1 and ScheduleEvent.objects.filter(state__question=question).count()==1)
            check('backend_next_date_after_Shanghai_today',question.next_review_date>django_timezone.localdate())
            check('backend_no_AI_role_and_applied_draft',not Message.objects.filter(session__owner=owner,role='assistant').exists() and Draft.objects.filter(owner=owner,status='applied').count()==1)
            report['next_review_date']=question.next_review_date.isoformat()
    except Exception as error:report['status']='failed';report['error']=str(error)if isinstance(error,DesktopError)else type(error).__name__
    finally:
        report.pop('_wizard_timer',None)
        if server:
            server.close();server.remove_state(paths.state)
            check('owned_service_threads_closed',not server.thread.is_alive())
            with socket.socket()as sock:sock.settimeout(1);check('owned_loopback_port_closed',sock.connect_ex(('127.0.0.1',server.port))!=0)
        if lock:lock.release()
        report['completed_utc']=datetime.now(timezone.utc).isoformat();output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'checks':len(report['checks']),'output':str(output),'error':report.get('error')},ensure_ascii=False));return 0 if report['status']=='passed'else 1
if __name__=='__main__':raise SystemExit(main())

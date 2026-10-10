"""Explicit end-to-end probe of the authorized isolated Django/MySQL copy.

The only login is a documented synthetic demo account. No AI configuration,
provider request, business-content update, schema migration or seed runs here.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading

from desktop.main import build_wsgi
from desktop.native_probe_tools import NativeProbeTools, wait_until
from desktop.runtime import DesktopError, InstanceLock, OwnedServer, RuntimePaths, wait_for_health, local_opener
from desktop.webview_window import open_window


def main(argv=None):
    parser = argparse.ArgumentParser(description="隔离合成账号的实际 Django/MySQL/WebView2 检查")
    parser.add_argument("--resource-dir", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--credentials-file", required=True)
    parser.add_argument("--output", default=str(Path(__file__).parent / "evidence" / "business-window-probe.json"))
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    report = {"started_utc":datetime.now(timezone.utc).isoformat(), "status":"running", "checks":[],
              "database_kind":"authorized_isolated_v2_development", "account_kind":"synthetic_demo",
              "real_ai_called":False, "api_key_configured":False, "schema_changed":False,
              "learning_tasks_questions_changed":False, "session_rows_may_be_created":True,
              "synthetic_chat_rows_may_be_created":True}
    server = None
    paths = None
    lock = None
    finished = threading.Event()

    def check(name, passed, detail=None):
        report["checks"].append({"name":name, "passed":bool(passed), "detail":detail})
        if not passed:
            raise DesktopError("实际业务窗口检查失败：" + name)

    def probe(window, guard):
        tools = NativeProbeTools(window)
        try:
            check("native_guard_and_filter", guard.installed.is_set() and guard.resource_filter_registered)
            check("actual_django_login_page", wait_until(lambda: tools.execute(
                "location.pathname === '/accounts/login/' && !!document.querySelector('[name=username]') && document.readyState === 'complete'")))
            login_capture = tools.capture_png(output.with_name(output.stem + "-login.png"))
            report["login_capture"] = login_capture
            check("native_window_contains_login_render", login_capture["bytes"] > 1000)
            check("offline_css_loaded", tools.execute(
                "Array.from(document.styleSheets).filter(s=>s.href && s.href.startsWith(location.origin+'/static/')).length >= 2"))
            tools.execute("""(()=>{const f=document.querySelector('form.stack-form');
f.elements.username.value='demo_student';f.elements.password.value='StudyDemo2026!';
setTimeout(()=>f.requestSubmit(),100);return true;})()""")
            check("synthetic_login_to_authenticated_dashboard", wait_until(lambda: tools.execute(
                "location.pathname==='/' && document.readyState==='complete' && !!document.querySelector('#mi-launcher') && document.querySelector('.username')?.innerText.includes('demo_student')"), seconds=12))
            check("image_editor_script_loaded", tools.execute("typeof StudyImages?.previewButton === 'function'"))
            check("mi_original_image_actual_512_pixels", wait_until(lambda: tools.execute(
                "(()=>{const i=document.querySelector('#mi-launcher img');return !!i && i.complete && i.naturalWidth===512 && i.naturalHeight===512;})()")))
            dashboard_capture = tools.capture_png(output.with_name(output.stem + "-dashboard.png"))
            report["dashboard_capture"] = dashboard_capture
            check("dashboard_and_mi_render_capture_created", dashboard_capture["bytes"] > 1000)
            tools.execute("document.querySelector('#mi-launcher').click()")
            check("assistant_opens_native_page_dialog", wait_until(lambda: tools.execute("document.querySelector('#mi-panel').open === true")))
            check("assistant_state_explicitly_unconnected", wait_until(lambda: tools.execute(
                "document.querySelector('#mi-provider-state').innerText==='AI 未连接' && document.querySelector('#mi-budget-summary').innerText.includes('不会调用 AI')")))
            check("persistent_session_list_loaded", wait_until(lambda: tools.execute(
                "document.querySelector('#mi-session').options.length > 0")))
            action_label = tools.execute("document.querySelector('#mi-send').innerText")
            report["unconnected_action_label"] = action_label
            check("unconnected_action_is_save_question", action_label == "保存问题")
            tools.execute("""(()=>{window.__desktopProbeConfig=null;fetch('/ai/config/',{credentials:'same-origin',redirect:'error'}).then(r=>{if(!r.ok)throw Error('config');return r.json();}).then(v=>{window.__desktopProbeConfig={enabled:v.enabled,configured:v.configured};}).catch(()=>{window.__desktopProbeConfig={error:true};});})()""")
            check("default_provider_disabled_and_unconfigured", wait_until(lambda: tools.execute(
                "window.__desktopProbeConfig?.enabled===false && window.__desktopProbeConfig?.configured===false")))
            report["provider_flags"] = tools.execute("window.__desktopProbeConfig")
            # Explicitly synthetic local chat only. The checked disabled state
            # prevents this probe from submitting to a configured AI provider.
            tools.execute("""(()=>{document.querySelector('#mi-text').value='桌面探测合成问题（AI 未连接）';document.querySelector('#mi-composer').requestSubmit();})()""")
            check("synthetic_question_saved_locally", wait_until(lambda: tools.execute(
                "Array.from(document.querySelectorAll('#mi-message-log [data-role=user] p')).some(p=>p.innerText==='桌面探测合成问题（AI 未连接）') && !document.querySelector('#mi-send').disabled"),seconds=12))
            check("unconfigured_response_is_system_record", tools.execute(
                "(()=>{const rows=Array.from(document.querySelectorAll('#mi-message-log [data-role]'));const last=rows.at(-1);return last?.dataset.role==='system' && last.querySelector('.mi-message-heading')?.innerText.includes('系统记录');})()"))
            check("no_python_api_exposed", tools.execute("Object.keys(window.pywebview?.api || {}).length===0"))
            context = tools.execute("({path:location.pathname,provider:document.querySelector('#mi-provider-state').innerText,sessionCount:document.querySelector('#mi-session').options.length,imageNaturalWidth:document.querySelector('#mi-launcher img').naturalWidth})")
            report["actual_ui_state"] = context
            authenticated_capture = tools.capture_png(output.with_name(output.stem + "-assistant.png"))
            report["authenticated_capture"] = authenticated_capture
            check("assistant_render_capture_created", authenticated_capture["bytes"] > 1000)
            tools.execute("document.querySelector('[data-mi-close]').click()")
            check("assistant_closes_without_navigation", wait_until(lambda: tools.execute("!document.querySelector('#mi-panel').open && location.pathname==='/'")))
            # Verify the exact temporary desktop identity with a separate CLI.
            # This invokes no DB configuration and sends no process-kill action.
            result = subprocess.run([sys.executable,"-m","desktop.main","--data-dir",str(paths.data),"--stop","--quiet"],
                                    cwd=paths.resources,capture_output=True,timeout=10)
            check("actual_cli_stop_identity_verified", result.returncode == 0)
            check("stop_requested_only_this_instance", server.stop_requested.is_set())
            report["status"] = "passed"
        except Exception as error:
            report["status"] = "failed"
            report["error"] = str(error) if isinstance(error, DesktopError) else "业务窗口验证异常"
            report["error_type"] = type(error).__name__
            try:
                # No input values, tokens, arbitrary message text or credentials.
                report["diagnostic"] = tools.execute("({path:location.pathname,title:document.title,state:document.readyState,provider:document.querySelector('#mi-provider-state')?.innerText,hasLauncher:!!document.querySelector('#mi-launcher')})")
            except Exception:
                report["diagnostic"] = "unavailable"
        finally:
            finished.set()
            if not server.stop_requested.is_set():
                window.destroy()

    try:
        paths = RuntimePaths.resolve(args.resource_dir,args.data_dir,args.credentials_file)
        paths.apply_environment("config.v2_development_settings")
        lock = InstanceLock(paths.lock).acquire()
        # Only this explicitly authorized development settings module is used.
        server = OwnedServer(build_wsgi()).start()
        health = wait_for_health(server.base_url,stopped=server.failed)
        check("actual_django_mysql_health_before_window", health.get("db") is True)
        server.write_state(paths.state)
        duplicate = subprocess.run([sys.executable,"-m","desktop.main","--resource-dir",str(paths.resources),
                                    "--data-dir",str(paths.data),"--credentials-file",str(paths.credentials),
                                    "--settings","config.v2_development_settings","--server-only","--quiet"],
                                   cwd=paths.resources,capture_output=True,timeout=15)
        check("actual_second_launch_is_single_instance", duplicate.returncode == 2)
        # Public assets are read over the exact owned local server with proxies disabled.
        client = local_opener()
        assets = {}
        for relative in ("css/app.css","css/v2.css","js/app.js","js/images.js","js/assistant.js","img/mi-avatar.png"):
            with client.open(server.base_url+"/static/"+relative,timeout=3) as response:
                body = response.read(5*1024*1024)
                check("static_200_"+relative,response.status==200 and len(body)>0)
                assets[relative] = {"bytes":len(body),"sha256":hashlib.sha256(body).hexdigest()}
        report["offline_assets"] = assets
        # A repeated probe must exercise login again instead of inheriting the
        # preceding synthetic session. Retain each private probe profile for
        # diagnosis; never include these profiles in the distributable.
        probe_profile = output.parent / "private" / ("business-profile-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"))
        probe_profile.mkdir(parents=True, exist_ok=False)
        open_window(server,probe_profile,smoke_seconds=60,on_ready=probe)
        finished.wait(5)
        if report["status"] == "running":
            raise DesktopError("业务窗口诊断未完成，已停止验证。")
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error) if isinstance(error, DesktopError) else "隔离业务窗口启动异常"
        report["error_type"] = type(error).__name__
    finally:
        if server:
            try:
                server.close()
                check("owned_server_thread_reclaimed",not server.thread.is_alive())
                check("owned_waitress_workers_reclaimed",not server.server.task_dispatcher.threads)
                with socket.socket() as connection:
                    connection.settimeout(1)
                    check("owned_port_closed",connection.connect_ex(("127.0.0.1",server.port))!=0)
            except Exception:
                report["status"]="failed"
                report["stop_error"]="自有本机服务未能确认干净退出。"
            if paths:
                server.remove_state(paths.state)
                check("temporary_control_state_removed",not paths.state.exists())
        if lock:
            lock.release()
            with InstanceLock(paths.lock):
                check("single_instance_lock_reacquirable",True)
        report["completed_utc"]=datetime.now(timezone.utc).isoformat()
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":report["status"],"checks":len(report["checks"]),"output":str(output)},ensure_ascii=False))
    return 0 if report["status"]=="passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Entry point for the source launcher and a future PyInstaller onedir build."""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import math
import os
import sys

if __package__ in {None, ""}:
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from desktop.runtime import (
    AlreadyRunning, DesktopError, InstanceLock, OwnedServer, RuntimePaths,
    request_stop, stop_state_path, wait_for_health,
)


def show_error(message, quiet=False):
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    if os.name == "nt" and not quiet:
        ctypes.windll.user32.MessageBoxW(None, message, "拾习 · 启动或退出", 0x10)


def build_wsgi():
    try:
        from django.core.wsgi import get_wsgi_application
        from django.conf import settings
        app = get_wsgi_application()
    except Exception:
        raise DesktopError("Django 配置加载失败。请检查本机数据库配置与依赖；凭据内容不会显示在错误框。") from None
    if settings.DEBUG:
        raise DesktopError("独立窗口交付模式要求 DEBUG=False，请检查 Django 配置。")
    # The production static middleware serves only collected assets. Refuse
    # a source-only fallback instead of enabling DEBUG/static discovery here.
    try:
        import whitenoise
    except ImportError:
        raise DesktopError("缺少离线静态资源服务依赖 WhiteNoise，请使用完整程序包。") from None
    if not settings.STATIC_ROOT or not os.path.isdir(settings.STATIC_ROOT):
        raise DesktopError("尚未收集离线静态资源；请先执行 collectstatic。")
    return whitenoise.WhiteNoise(app, root=settings.STATIC_ROOT,
                                prefix=settings.STATIC_URL, autorefresh=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description="拾习本机独立窗口；不启动或停止 MySQL 服务。")
    parser.add_argument("--resource-dir")
    parser.add_argument("--data-dir")
    parser.add_argument("--credentials-file")
    parser.add_argument("--settings", default="config.settings",
                        choices=("config.settings", "config.v2_development_settings"))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--stop", action="store_true", help="验证并请求本次窗口协作退出")
    parser.add_argument("--check", action="store_true", help="只检查路径、依赖与运行库，不连接数据库")
    parser.add_argument("--diagnose", action="store_true", help="只读环境诊断，未配置也能检查内置依赖")
    parser.add_argument("--diagnose-database", action="store_true", help="诊断时用已有安全配置只读核对数据库和结构")
    parser.add_argument("--diagnose-output", help="将无凭据值的诊断JSON写入一个全新文件")
    parser.add_argument("--server-only", action="store_true", help="本机服务验证入口，不打开浏览器")
    parser.add_argument("--smoke-seconds", type=float, default=0, help="窗口验证后自动退出，默认不计时")
    parser.add_argument("--quiet", action="store_true", help="仅用于脚本验证，不弹错误框")
    parser.add_argument("--setup", action="store_true", help="打开本机环境检查和人工配置路径向导")
    parser.add_argument("--start-or-setup", action="store_true", help="配置可用时启动，否则打开配置向导")
    parser.add_argument("--prefer-saved-data", action="store_true", help="沿用本人此前明确确认的数据目录")
    parser.add_argument("--initialize-new-empty-database", action="store_true", help="本人确认的新电脑空库初始化；已有同名库一律拒绝")
    parser.add_argument("--confirm-existing-account-dml-grant", action="store_true", help="确认向已有 localhost 应用账户授予四项 DML")
    parser.add_argument("--seed-synthetic-demo", action="store_true", help="仅本次新建空库可填入明确标记的演示数据")
    parser.add_argument("--initialization-output", help="将无秘密的初始化结果写入全新 JSON 文件")
    args = parser.parse_args(argv)
    server = None
    lock = None
    paths = None
    try:
        if args.initialize_new_empty_database:
            from pathlib import Path
            if args.stop or args.setup or args.start_or_setup or args.diagnose or args.check or args.server_only:
                raise DesktopError("初始化不能与启动、停止或诊断组合执行。")
            if args.settings != 'config.settings':
                raise DesktopError("新电脑初始化只接受标准本机配置。")
            output = Path(args.initialization_output) if args.initialization_output else None
            if output and (not output.is_absolute() or output.exists() or not output.parent.is_dir()):
                raise DesktopError("初始化报告必须是现有目录中的全新绝对路径文件。")
            from desktop.bootstrap import initialize_new_installation
            resources = Path(args.resource_dir or os.environ.get('STUDY_RESOURCE_DIR')
                or getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent)).resolve()
            outcome = initialize_new_installation(resources, args.data_dir, args.credentials_file,
                create_confirmed=True, grant_confirmed=args.confirm_existing_account_dml_grant,
                synthetic_demo=args.seed_synthetic_demo)
            import json
            if output:
                with output.open('x', encoding='utf-8') as stream:
                    json.dump(outcome, stream, ensure_ascii=False, indent=2)
            if sys.stdout is not None:
                print(json.dumps(outcome, ensure_ascii=False))
            elif os.name == 'nt' and not args.quiet:
                ctypes.windll.user32.MessageBoxW(None, "初始化完成。可从“启动拾习”进入；"
                    "若选演示数据，账号为 demo_student，密码见首次启动说明。",
                    "拾习 · 新电脑初始化", 0x40)
            return 0
        if args.seed_synthetic_demo or args.confirm_existing_account_dml_grant or args.initialization_output:
            raise DesktopError("初始化选项只能与明确的新建空库操作一起使用。")
        if args.prefer_saved_data and args.settings=='config.settings':
            from desktop.setup_wizard import remembered_data_dir
            args.data_dir=remembered_data_dir()or args.data_dir
        if args.setup or args.start_or_setup:
            from pathlib import Path
            from desktop.preflight import diagnose
            from desktop.setup_wizard import run_wizard
            resources=Path(args.resource_dir or os.environ.get('STUDY_RESOURCE_DIR')or getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent)).resolve()
            report=diagnose(resources,args.data_dir,args.credentials_file,True,args.settings)
            if args.setup or not report['ready_to_launch']:
                choice=run_wizard(resources,args.data_dir,args.credentials_file,settings_module=args.settings)
                if not choice:return 0
                args.data_dir=choice['data_dir'];args.credentials_file=choice['credentials_file']
        if args.diagnose:
            import json
            from pathlib import Path
            from desktop.preflight import diagnose
            report=diagnose(args.resource_dir,args.data_dir,args.credentials_file,args.diagnose_database,args.settings)
            payload=json.dumps(report,ensure_ascii=False,indent=2)
            if args.diagnose_output:
                with Path(args.diagnose_output).open('x',encoding='utf-8')as output:output.write(payload)
            elif sys.stdout is not None:print(payload)
            else:show_error('请使用外层“环境检查与首次配置”，或指定 --diagnose-output 保存检查结果。',quiet=args.quiet)
            return 0 if report['ready_to_launch']else 3
        if args.stop:
            request_stop(stop_state_path(args.data_dir))
            if sys.stdout is not None:
                print("已向核验一致的独立窗口发送退出请求。")
            return 0
        paths = RuntimePaths.resolve(args.resource_dir, args.data_dir, args.credentials_file)
        paths.apply_environment(args.settings)
        if args.check:
            missing = [name for name in ("django", "waitress", "webview", "whitenoise")
                       if importlib.util.find_spec(name) is None]
            if missing:
                raise DesktopError("依赖缺失：" + ", ".join(missing))
            from desktop.webview_window import webview2_installed
            if not webview2_installed():
                raise DesktopError("未检测到 Windows WebView2 Runtime。")
            print("本机路径、依赖与 WebView2 检查通过；尚未验证数据库连接。")
            return 0
        if not math.isfinite(args.smoke_seconds) or args.smoke_seconds < 0:
            raise DesktopError("自动退出时间必须是有限的非负数。")
        lock = InstanceLock(paths.lock).acquire()
        server = OwnedServer(build_wsgi(), port=args.port).start()
        wait_for_health(server.base_url, stopped=server.failed)
        server.write_state(paths.state)
        if args.server_only:
            print("本机服务与数据库启动检查通过。")
            while not server.stop_requested.wait(.25):
                if server.failed():
                    raise DesktopError("本机服务意外退出。")
        else:
            from desktop.webview_window import open_window
            open_window(server, paths.browser_profile, smoke_seconds=args.smoke_seconds)
        return 0
    except AlreadyRunning as error:
        show_error(str(error), quiet=args.quiet)
        return 2
    except DesktopError as error:
        show_error(str(error), quiet=args.quiet)
        return 1
    except KeyboardInterrupt:
        return 0
    except Exception:
        show_error("独立窗口发生未预期错误。请保留学习数据目录并查看交付说明；没有停止共享数据库。", quiet=args.quiet)
        return 1
    finally:
        if server:
            try:
                server.close()
            except DesktopError as error:
                show_error(str(error), quiet=args.quiet)
                # Do not report a clean stop when our own threads remain alive.
                return 1
            if paths:
                server.remove_state(paths.state)
        if lock:
            lock.release()


if __name__ == "__main__":
    raise SystemExit(main())

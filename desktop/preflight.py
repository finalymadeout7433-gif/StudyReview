"""Read-only first-start checks; no Django setup, secrets creation or schema writes."""
from __future__ import annotations
import importlib
import json
import os
from pathlib import Path
import sys
from .runtime import inside,child_path,DesktopError

TABLES = {
    'auth_group','auth_group_permissions','auth_permission','auth_user','auth_user_groups','auth_user_user_permissions',
    'django_content_type','django_migrations','django_session',
    'learning_course','learning_knowledgepoint','learning_task','learning_wrongquestion','learning_questionknowledgepoint','learning_reviewrecord',
    'attachments_attachment','attachments_questionimage','attachments_reviewimagemanifest','attachments_reviewimagesnapshot',
    'assistant_chatsession','assistant_message','assistant_messageattachment','assistant_draft',
    'scheduling_schedulingstate','scheduling_scheduleevent','ai_gateway_account','ai_gateway_requestledger','ai_gateway_messagecontext',
}
TRIGGERS = {'study_review_no_update','study_review_no_delete','study_point_same_course_insert','study_point_same_course_update',
    'study_task_no_move','study_wrongquestion_no_move','study_knowledgepoint_no_move',
    'att_image_no_update','att_image_no_delete','att_manifest_no_update','att_manifest_no_delete',
    'att_snapshot_no_update','att_snapshot_no_delete','study_schedule_no_update','study_schedule_no_delete'}

def diagnose(resource_dir=None, data_dir=None, credentials_file=None, database=False, settings_module='config.settings'):
    resources=Path(resource_dir or os.environ.get('STUDY_RESOURCE_DIR') or getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent)).resolve()
    selected_data=data_dir or os.environ.get('STUDY_DATA_DIR')
    if not selected_data:
        local=os.environ.get('LOCALAPPDATA')
        selected_data=(Path(local) if local else Path.home())/'StudyReview'/'data'
    data=Path(selected_data).resolve()
    report={'app':'studyreview','version':'2.0','read_only':True,'ready_to_launch':False,'configured':False,
        'database_requested':bool(database),'database_checked':False,'database_ready':False,'checks':[],
        'credentials_values_recorded':False,'real_ai_called':False}
    def check(code,passed,message):
        report['checks'].append({'code':code,'passed':bool(passed),'message':message})
    check('program_resources',all((resources/name).is_file()for name in ('templates/base.html','staticfiles/css/app.css','staticfiles/css/v2.css','staticfiles/js/assistant.js','staticfiles/img/mi-avatar.png')),'程序模板、离线样式、助手脚本和咪头像完整。')
    check('separate_data_directory',not inside(data,resources)and(not getattr(sys,'frozen',False)or not inside(data,Path(sys.executable).resolve().parent)),'学习数据须位于程序目录之外；诊断不会创建数据目录。')
    for name in ('django','MySQLdb','PIL.Image','fsrs','waitress','whitenoise','webview'):
        try:importlib.import_module(name);passed=True
        except Exception:passed=False
        check('dependency_'+name,passed,'内置依赖 '+name+(' 可加载。'if passed else ' 无法加载，请使用完整程序包并核对系统运行库。'))
    from .webview_window import webview2_installed
    check('webview2',webview2_installed(),'需要本机 WebView2 Runtime；本工具只检查，不下载或安装。')
    if not all(item['passed']for item in report['checks']):return report
    # Use the same containment gate as formal startup before reading *any*
    # reference/credentials or performing a database check. The selected DATA
    # may contain a private junction or individually redirected JSON files.
    try:
        private=child_path(data,'private')
        runtime=child_path(private,'runtime.json')
        development_file=child_path(private,'development-environment.json')
    except (DesktopError,OSError,RuntimeError):
        check('private_path_boundary',False,'私有配置路径超出所选学习数据目录或无法安全核验；未读取配置，未连接数据库。')
        return report
    check('private_path_boundary',True,'私有目录和配置引用均在所选学习数据目录内；尚未读取凭据正文。')
    selected=credentials_file or os.environ.get('STUDY_CREDENTIALS_FILE')
    if not selected and runtime.is_file():
        try:
            selected=json.loads(runtime.read_text(encoding='utf-8-sig')).get('credentials_file')
            if not isinstance(selected,str)or not selected:raise ValueError
            candidate=Path(selected).expanduser()
            if not candidate.is_absolute():
                candidate=(runtime.parent/candidate).resolve()
                if not inside(candidate,runtime.parent):raise ValueError
            selected=str(candidate)
        except (OSError,ValueError,TypeError,AttributeError):
            check('configuration_reference',False,'私有 runtime.json 路径引用格式不正确；原文件未改。');return report
    if not selected:
        check('configuration_reference',False,'尚未配置数据库。请本人选择已有本机安全配置并确认保存路径；当前不会创建账户或数据库。');return report
    try:
        if not isinstance(selected,(str,os.PathLike)):raise ValueError
        credential_path=Path(selected).expanduser().resolve()
        if not credential_path.is_file():raise ValueError
    except (OSError,ValueError,TypeError):
        check('configuration_reference',False,'所选本机安全配置文件不存在或路径无效。');return report
    report['configured']=True
    check('configuration_reference',True,'已有本机配置路径可读；报告不包含账户、密码或密钥值。')
    if not database:return report
    try:
        config=json.loads(credential_path.read_text(encoding='utf-8-sig'))
        if not isinstance(config,dict)or config.get('host')not in ('127.0.0.1','localhost'):raise ValueError
        if type(config.get('port'))is not int or not 1<=config['port']<=65535:raise ValueError
        if not all(isinstance(config.get(key),str)and config[key].strip()for key in ('application_user','application_password')):raise ValueError
        name='study_review_dev';user=config['application_user'];password=config['application_password']
        if settings_module=='config.v2_development_settings':
            development=json.loads(development_file.read_text(encoding='utf-8-sig'))
            name=development['database']
            if not isinstance(name,str)or not name.startswith('study_review_v2_dev_'):raise ValueError
            user=config['administrator_user'];password=config['administrator_password']
        elif settings_module!='config.settings':raise ValueError
    except (OSError,ValueError,TypeError,AttributeError,KeyError):
        check('database_configuration',False,'配置须包含本机host、整数port和非空应用账户/密码；值不显示。请本人核对配置，不使用无密码数据库。');return report
    import MySQLdb
    connection=None
    report['database_checked']=True
    try:
        connection=MySQLdb.connect(host=config['host'],port=config['port'],user=user,passwd=password,db=name,charset='utf8mb4',connect_timeout=4,read_timeout=4)
        with connection.cursor()as cursor:
            cursor.execute('SELECT DATABASE(),VERSION()');actual,version=cursor.fetchone()
            check('mysql_connection',actual==name,'本机 MySQL 连接成功，目标库身份匹配。')
            report['mysql_version']=str(version)
            cursor.execute('SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s',(name,));tables={row[0]for row in cursor.fetchall()}
            cursor.execute('SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s',(name,));triggers={row[0]for row in cursor.fetchall()}
            missing=sorted(TABLES-tables)
            report['missing_tables']=missing
            check('schema_tables',not missing,'需要完整 V2 表结构；缺失时先按全新空库初始化/恢复说明操作，不覆盖现有库。')
            check('history_guards',not(TRIGGERS-triggers),'需要15个历史和关系保护触发器；由既有本机管理员核验迁移与权限。')
            if 'django_migrations'in tables:
                cursor.execute('SELECT COUNT(*) FROM django_migrations WHERE app=%s AND name=%s',('scheduling','0003_override_null_guard'))
                check('migration_marker',cursor.fetchone()[0]==1,'V2迁移记录完整；仅导入结构SQL不能代替正式迁移或完整数据恢复。')
        report['database_ready']=all(item['passed']for item in report['checks'])
        report['ready_to_launch']=report['database_ready']
    except Exception:
        check('mysql_connection',False,'本机数据库不可用或认证未通过。请本人检查MySQL是否运行、端口、库名和安全配置；未创建或覆盖数据，错误不含密码。')
    finally:
        if connection is not None:connection.close()
    return report

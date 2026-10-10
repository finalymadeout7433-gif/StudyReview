"""Native first-start UI; credentials stay in the user's existing private file."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid
from .runtime import DesktopError,InstanceLock,child_path,inside

def preference_path():
    local=os.environ.get('LOCALAPPDATA')
    if not local:raise DesktopError('无法定位本人应用数据目录，请明确选择学习数据目录。')
    return Path(local)/'StudyReview'/'launcher.json'

def remembered_data_dir(preferences=None):
    file=Path(preferences)if preferences else preference_path()
    try:
        value=json.loads(file.read_text(encoding='utf-8-sig'))['data_dir']
        candidate=Path(value)
        if not isinstance(value,str)or not candidate.is_absolute():return None
        return str(candidate.resolve())
    except (OSError,ValueError,TypeError,KeyError,AttributeError):return None

def configuration_reference(data_dir):
    try:
        value=json.loads(child_path(Path(data_dir),'private','runtime.json').read_text(encoding='utf-8-sig'))['credentials_file']
        return value if isinstance(value,str)else ''
    except (OSError,ValueError,TypeError,KeyError,DesktopError):return ''

def _secure_new_directory(path):
    if os.name!='nt':return
    sid=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],capture_output=True,text=True,check=True).stdout.strip()
    if not sid.startswith('S-1-5-'):raise DesktopError('不能确认本人目录权限，未保存路径。')
    result=subprocess.run(['icacls.exe',str(path),'/inheritance:r','/grant:r','*'+sid+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],capture_output=True)
    if result.returncode:raise DesktopError('不能保护新私人目录，未保存配置路径。')

def persist_reference(resources,data_dir,credentials_file,*,confirmed=False,replace_confirmed=False,preferences=None):
    """Only references are read/written. An explicit user action is mandatory."""
    if not confirmed:raise DesktopError('请本人勾选确认保存路径；不会自动保存。')
    resources=Path(resources).resolve();data=Path(data_dir).resolve();credentials=Path(credentials_file).resolve()
    bundle=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False)else resources
    if inside(data,resources)or inside(data,bundle):raise DesktopError('学习数据目录必须在程序目录之外。')
    if not credentials.is_file():raise DesktopError('请本人选择已存在的本机安全配置文件。')
    if inside(credentials,resources)or inside(credentials,bundle):raise DesktopError('数据库安全配置也应私存于程序目录之外。')
    private=child_path(data,'private');runtime=child_path(private,'runtime.json')
    old=None;same=False
    if runtime.exists():
        try:
            old=runtime.read_bytes();previous=json.loads(old.decode('utf-8-sig'))
            if set(previous)!={'credentials_file'}or not isinstance(previous['credentials_file'],str):raise ValueError
        except (OSError,ValueError,TypeError,AttributeError):raise DesktopError('已有路径配置格式不正确；原文件不覆盖，请本人先检查。')from None
        if Path(previous['credentials_file']).is_absolute()and Path(previous['credentials_file']).resolve()==credentials:
            same=True
        if not same and not replace_confirmed:raise DesktopError('已有其他配置引用，请本人明确确认替换；原文件未改。')
    was_new=not private.exists();private.mkdir(parents=True,exist_ok=True)
    if was_new:_secure_new_directory(private)
    payload=json.dumps({'credentials_file':str(credentials)},ensure_ascii=False,indent=2)
    with InstanceLock(child_path(private,'.setup-reference.lock')):
        if old is not None and runtime.read_bytes()!=old:raise DesktopError('路径配置已变化，请重新读取后确认。')
        if not same:
            if old is None:
                try:
                    with runtime.open('x',encoding='utf-8')as stream:stream.write(payload)
                except FileExistsError:raise DesktopError('已有其他窗口写入配置，未覆盖，请重新读取。')from None
            else:
                backup=child_path(private,'runtime-reference-before-'+uuid.uuid4().hex+'.json')
                with backup.open('xb')as stream:stream.write(old)
                temp=child_path(private,'runtime-reference-new-'+uuid.uuid4().hex+'.json')
                with temp.open('x',encoding='utf-8')as stream:stream.write(payload)
                os.replace(temp,runtime)
    selected=Path(preferences)if preferences else preference_path()
    saved=False
    try:
        parent_new=not selected.parent.exists();selected.parent.mkdir(parents=True,exist_ok=True)
        if parent_new:_secure_new_directory(selected.parent)
        temp_pref=selected.with_name('launcher-reference-new-'+uuid.uuid4().hex+'.json')
        with temp_pref.open('x',encoding='utf-8')as stream:json.dump({'data_dir':str(data)},stream,ensure_ascii=False,indent=2)
        os.replace(temp_pref,selected);saved=True
    except (OSError,DesktopError,subprocess.SubprocessError):pass
    return {'runtime':str(runtime),'changed':not same,'preferences_saved':saved}

def run_wizard(resources,data_dir=None,credentials_file=None,*,settings_module='config.settings',on_shown=None):
    """Return the user's launch selection, or None when the window is closed."""
    import clr
    clr.AddReference('System.Windows.Forms');clr.AddReference('System.Drawing')
    from System import Action
    from System.Drawing import Color,Font,Size,Point,Bitmap
    from System.Windows.Forms import (Application,Form,Label,TextBox,Button,CheckBox,
        FolderBrowserDialog,OpenFileDialog,DialogResult,FormStartPosition,Padding)
    from .preflight import diagnose
    # Pinned pywebview initializes text rendering before the first Win32 handle.
    # Do it here so its later application window can reuse that initialization.
    from webview.platforms import winforms
    winforms.setup_app()
    form=Form();form.Text='拾习 · 环境检查与首次配置';form.ClientSize=Size(830,660)
    form.MinimumSize=Size(760,620);form.StartPosition=FormStartPosition.CenterScreen
    form.BackColor=Color.FromArgb(247,242,237);form.Font=Font('Microsoft YaHei UI',10)
    def label(text,x,y,width,height):
        item=Label();item.Text=text;item.Location=Point(x,y);item.Size=Size(width,height);form.Controls.Add(item);return item
    title=label('欢迎使用拾习',28,20,760,48);title.Font=Font('Microsoft YaHei UI',23)
    label('本机学习与复习软件。咪是应用内的学习助手；联网回答由本人配置的 DeepSeek 提供。',30,80,765,44)
    label('1 选择程序之外的私人学习数据目录',30,136,755,28)
    data=TextBox();data.Location=Point(30,170);data.Size=Size(650,30)
    data.Text=str(data_dir or remembered_data_dir()or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'StudyReview'/'data');form.Controls.Add(data)
    choose_data=Button();choose_data.Text='选择目录';choose_data.Location=Point(690,167);choose_data.Size=Size(105,34);form.Controls.Add(choose_data)
    label('2 选择本人已有的本机数据库安全配置（只保存路径，不显示或复制密码）',30,216,770,28)
    credentials=TextBox();credentials.Location=Point(30,250);credentials.Size=Size(650,30)
    credentials.Text=str(credentials_file or configuration_reference(data.Text));form.Controls.Add(credentials)
    choose_config=Button();choose_config.Text='选择文件';choose_config.Location=Point(690,247);choose_config.Size=Size(105,34);form.Controls.Add(choose_config)
    label('尚无配置时，先按说明由本人准备本机 MySQL 及安全文件；此向导不建库、不创建账户、不调用 AI。',30,288,770,42)
    confirm=CheckBox();confirm.Text='我确认使用所选已有配置并保存路径引用，同时记住所选学习数据目录。'
    confirm.Location=Point(30,335);confirm.Size=Size(770,28);confirm.Checked=False;form.Controls.Add(confirm)
    replace=CheckBox();replace.Text='若已有其他配置引用，我明确确认替换（原路径文件另存备份）。'
    replace.Location=Point(30,368);replace.Size=Size(770,28);replace.Checked=False;form.Controls.Add(replace)
    status=label('先点击只读检查。检查不会创建私人目录、读取密码回显或修改数据库。',30,414,770,154)
    status.BackColor=Color.FromArgb(255,252,248);status.Padding=Padding(10)
    check=Button();check.Text='只读检查';check.Location=Point(30,590);check.Size=Size(145,42);form.Controls.Add(check)
    save=Button();save.Text='确认保存路径';save.Location=Point(191,590);save.Size=Size(160,42);save.Enabled=False;form.Controls.Add(save)
    launch=Button();launch.Text='打开拾习';launch.Location=Point(603,590);launch.Size=Size(192,42);launch.Enabled=False;form.Controls.Add(launch)
    result={'selection':None,'report':None};busy={'value':False}
    def changed(sender,event):result['report']=None;launch.Enabled=False;save.Enabled=confirm.Checked and not busy['value']
    data.TextChanged+=changed;credentials.TextChanged+=changed;confirm.CheckedChanged+=changed
    def select_directory(sender,event):
        dialog=FolderBrowserDialog();dialog.Description='选择独立私人学习数据目录';dialog.SelectedPath=data.Text
        if dialog.ShowDialog(form)==DialogResult.OK:data.Text=dialog.SelectedPath
        dialog.Dispose()
    def select_file(sender,event):
        dialog=OpenFileDialog();dialog.Title='本人选择已有本机数据库安全配置';dialog.Filter='JSON 配置文件 (*.json)|*.json';dialog.CheckFileExists=True
        if dialog.ShowDialog(form)==DialogResult.OK:credentials.Text=dialog.FileName
        dialog.Dispose()
    choose_data.Click+=select_directory;choose_config.Click+=select_file
    def perform_check(sender,event):
        if busy['value']:return
        busy['value']=True;check.Enabled=False;save.Enabled=False;launch.Enabled=False;status.Text='正在检查内置依赖、运行库与本人所选本机数据库，仅执行读取…'
        chosen_data,chosen_credentials=data.Text,credentials.Text
        def worker():
            try:report=diagnose(resources,chosen_data,chosen_credentials or None,True,settings_module)
            except Exception:report={'ready_to_launch':False,'checks':[{'passed':False,'message':'检查无法完成；请核对路径或运行库，配置内容没有显示。'}]}
            def update():
                if form.IsDisposed:return
                busy['value']=False;check.Enabled=True;save.Enabled=confirm.Checked
                if data.Text!=chosen_data or credentials.Text!=chosen_credentials:status.Text='选择已变化，请重新检查。';return
                result['report']=report;launch.Enabled=report['ready_to_launch']
                failed=[row['message']for row in report['checks']if not row['passed']]
                status.Text=('检查通过，可以打开拾习。尚未配置 AI，不代表已识别图片或在线连接。\n打开软件会创建本机必要缓存和会话目录。'if not failed else'需要处理：\n'+'\n'.join(failed[:3]))
            try:
                if not form.IsDisposed:form.BeginInvoke(Action(update))
            except Exception:pass  # The user may close the window during a read.
        threading.Thread(target=worker,name='StudyReview-setup-readonly',daemon=True).start()
    def save_reference(sender,event):
        try:
            outcome=persist_reference(resources,data.Text,credentials.Text,confirmed=confirm.Checked,replace_confirmed=replace.Checked)
            status.Text='配置路径已保存；数据库密码和密钥没有复制。'+('已记住数据目录。'if outcome['preferences_saved']else'以后请沿用当前数据目录。')
            confirm.Checked=False;replace.Checked=False;perform_check(None,None)
        except Exception as error:status.Text=str(error)if isinstance(error,DesktopError)else'无法保存路径引用；已有配置未静默覆盖，请检查目录权限。'
    def start(sender,event):
        if not result['report']or not result['report']['ready_to_launch']:return
        result['selection']={'data_dir':data.Text,'credentials_file':credentials.Text or configuration_reference(data.Text)};form.Close()
    check.Click+=perform_check;save.Click+=save_reference;launch.Click+=start
    if on_shown:form.Shown+=lambda sender,event:on_shown(form,{'data':data,'credentials':credentials,'confirm':confirm,'replace':replace,'check':check,'save':save,'launch':launch,'status':status})
    Application.Run(form);form.Dispose();return result['selection']

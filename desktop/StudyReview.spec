# A local onedir candidate. User data, credentials and model keys are excluded.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata
ROOT = Path(SPECPATH).resolve().parent
apps = ('learning','attachments','assistant','scheduling','ai_gateway')
hidden = ['config.settings','config.v2_development_settings','config.v2_migration_settings','config.local_runtime',
          'config.urls','config.health','config.wsgi',
          'desktop.runtime','desktop.webview_window','desktop.preflight','desktop.setup_wizard','desktop.bootstrap',
          'scripts.initialize_v2_mysql','MySQLdb',
          'django.db.backends.mysql','django.contrib.auth','django.contrib.contenttypes',
          'django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles',
          'django.template.backends.django','django.contrib.auth.context_processors',
          'django.contrib.messages.context_processors','django.template.context_processors',
          'django.middleware.security','django.middleware.common','django.middleware.csrf',
          'django.middleware.clickjacking','django.contrib.sessions.middleware',
          'django.contrib.auth.middleware','django.contrib.messages.middleware']
for app in apps:
    hidden += collect_submodules(app, filter=lambda name: '.tests' not in name and '.test_' not in name)
data = [(str(ROOT/'templates'),'templates'),(str(ROOT/'staticfiles'),'staticfiles'),
        (str(ROOT/'materials'/'desktop-licenses'),'licenses'),
        (str(ROOT/'materials'/'desktop-dependency-manifest.json'),'.')]
for app in (*apps,'django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions'):
    if app in apps:
        migration_dir = ROOT/app/'migrations'
        for file in migration_dir.glob('*.py'):
            data.append((str(file),f'{app}/migrations'))
for library in ('django','webview','fsrs','clr_loader','pythonnet'):
    data += collect_data_files(library)
for distribution in ('Django','mysqlclient','Pillow','fsrs','pywebview','waitress','whitenoise','pythonnet','clr_loader'):
    data += copy_metadata(distribution)
a=Analysis([str(ROOT/'desktop'/'main.py')],pathex=[str(ROOT)],
           binaries=[],datas=data,hiddenimports=hidden,hookspath=[],hooksconfig={},
           runtime_hooks=[],excludes=['torch','tensorflow','numpy','pandas',
               'django.contrib.gis','PyQt5','PyQt6','PySide2','PySide6','webview.platforms.qt',
               'webview.platforms.gtk','webview.platforms.cocoa','cefpython3'],
           noarchive=False,optimize=0)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='StudyReview',
        debug=False,bootloader_ignore_signals=False,strip=False,upx=False,
        console=False,disable_windowed_traceback=True)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='StudyReview')

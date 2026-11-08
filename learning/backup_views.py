"""Account-only export and read-only preflight. No web restore endpoint."""
import shutil
import uuid
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .archive import ArchiveError, MAX_ZIP, export_account, inspect_archive, target_report


class InspectForm(forms.Form):
    archive = forms.FileField(label='选择账号学习资料包', help_text='ZIP，最大128MB。这里只检查，不导入、不覆盖当前资料。', widget=forms.ClearableFileInput(attrs={'accept': '.zip'}))

    def clean_archive(self):
        file = self.cleaned_data['archive']
        if file.size > MAX_ZIP:
            raise forms.ValidationError('文件超过128MB上限。')
        return file


def response(request, context, status=200):
    result = render(request, 'learning/backup.html', {'section': 'backup', 'title': '资料备份',
                    'inspect_form': InspectForm(), **context}, status=status)
    result['Cache-Control'] = 'no-store'
    return result


@login_required
def workspace(request):
    context = {}
    if request.method == 'POST':
        form = InspectForm(request.POST, request.FILES)
        context['inspect_form'] = form
        if form.is_valid():
            try:
                checked = inspect_archive(form.cleaned_data['archive'])
                context['inspection'] = checked.summary()
                context['target'] = target_report(request.user)
            except ArchiveError as exc:
                form.add_error('archive', str(exc))
    return response(request, context)


def save_local(user, stream):
    root = Path(settings.PRIVATE_DATA_ROOT).resolve()
    folder = root / 'exports' / str(user.pk)
    for path in (root / 'exports', folder):
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
            raise OSError('Unsafe export directory')
        path.mkdir(exist_ok=True)
    target = folder / ('learning-backup-' + timezone.localtime().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex + '.zip')
    stream.seek(0)
    with target.open('xb') as output:
        try:
            shutil.copyfileobj(stream, output, 1024 * 1024)
        except OSError:
            output.close(); target.unlink(missing_ok=True); raise
    return target


@login_required
@require_POST
def export(request):
    stream = None
    try:
        stream = export_account(request.user)
        if settings.DESKTOP_NATIVE:
            path = save_local(request.user, stream)
            stream.close()
            return response(request, {'saved_path': str(path)})
        result = FileResponse(stream, as_attachment=True, filename='studyreview-account-learning.zip', content_type='application/zip')
        result['Cache-Control'] = 'no-store'
        return result
    except ArchiveError as exc:
        if stream: stream.close()
        return response(request, {'export_error': str(exc)}, 400)
    except (OSError, ValueError):
        if stream: stream.close()
        return response(request, {'export_error': '导出未完成，请检查媒体文件、可写空间和数据目录；原学习资料没有改动。'}, 503)

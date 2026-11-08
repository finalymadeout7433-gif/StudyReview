"""Versioned account-scoped focus export. Not a full application backup."""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.http import Http404
from django.shortcuts import render
from pathlib import Path
import json
import uuid
from .models import Course, Task, FocusSession, FocusInterval

def snapshot(user):
    # Lock the same account row used by focus commands for a coherent timer export.
    from django.contrib.auth import get_user_model
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        sessions=list(FocusSession.objects.select_for_update().filter(owner=user).values('id','course_id','task_id','task_title','target_seconds','status','started_at','ended_at'))
        ids=[s['id'] for s in sessions]
        course_ids={s['course_id'] for s in sessions if s['course_id']}
        task_ids={s['task_id'] for s in sessions if s['task_id']}
        return {'format':'studyreview.focus','version':1,'exported_at':timezone.now(),
            'scope':'focus_only','restore_note':'专注记录与关联课程/任务参考，不含错题、复习、附件、聊天或账号凭据；不能替代完整SQL与媒体备份。活动记录包含未结束区间，读取统计应以exported_at为截止。',
            'courses':list(Course.objects.filter(owner=user,pk__in=course_ids).values('id','name','is_archived')),
            'tasks':list(Task.objects.filter(course__owner=user,pk__in=task_ids).values('id','course_id','title','status')),
            'sessions':sessions,'intervals':list(FocusInterval.objects.filter(session_id__in=ids).values('id','session_id','started_at','ended_at'))}

@login_required
@require_GET
def export(request):
    response=JsonResponse(snapshot(request.user),json_dumps_params={'ensure_ascii':False,'indent':2})
    response['Content-Disposition']='attachment; filename="studyreview-focus-v1.json"'
    response['Cache-Control']='no-store'
    return response


def save_local(user):
    """Save an account-scoped snapshot without permitting WebView downloads.

    No caller-controlled destination, no overwrite, and no credentials in JSON.
    Only a newly created partial file is removed if its write fails.
    """
    payload=json.dumps(snapshot(user),cls=DjangoJSONEncoder,ensure_ascii=False,indent=2)
    root=Path(settings.PRIVATE_DATA_ROOT).resolve()
    folder=root/'exports'/str(user.pk)
    for item in (root/'exports',folder):
        if item.is_symlink() or getattr(item,'is_junction',lambda:False)():
            raise OSError('Export directory is a link')
        if not item.resolve().is_relative_to(root):
            raise OSError('Export directory is outside data')
        item.mkdir(exist_ok=True)
    target=folder/('focus-'+timezone.localtime().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex+'.json')
    with target.open('x',encoding='utf-8') as stream:
        try:stream.write(payload)
        except OSError:
            stream.close();target.unlink(missing_ok=True);raise
    return target


@login_required
@require_POST
def export_local(request):
    if not settings.DESKTOP_NATIVE:raise Http404
    context={'title':'导出专注记录','section':'focus'}
    try:context['export_path']=str(save_local(request.user))
    except OSError:
        context['export_error']='未能保存文件，请检查学习数据目录的可写权限和剩余空间，再重试。专注记录仍保留在数据库中。'
    response=render(request,'learning/focus_export.html',context,status=503 if context.get('export_error') else 200)
    response['Cache-Control']='no-store'
    return response

"""Server-clock focus sessions. Account row locks serialize multi-tab commands."""
from datetime import datetime, time, timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse, Http404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import Course, Task, FocusSession, FocusInterval


def seconds(session, now):
    total = sum(max(0, ((i.ended_at or now)-i.started_at).total_seconds()) for i in session.intervals.all())
    return min(session.target_seconds, int(total))


def settle(session, now, finish=False):
    intervals = list(session.intervals.all())
    used = sum((i.ended_at-i.started_at).total_seconds() for i in intervals if i.ended_at)
    opened = next((i for i in intervals if i.ended_at is None), None)
    if opened:
        deadline = opened.started_at + timedelta(seconds=max(0, session.target_seconds-used))
        opened.ended_at = max(opened.started_at, min(now, deadline))
        opened.save(update_fields=['ended_at'])
    session.status = 'finished' if finish or seconds(session, now) >= session.target_seconds else 'paused'
    session.ended_at = now if session.status == 'finished' else None
    session.save(update_fields=['status','ended_at'])


@transaction.atomic
def command(user, action, session_id=None, course_id=None, minutes=25, now=None, task_id=None):
    now = now or timezone.now()
    get_user_model().objects.select_for_update().get(pk=user.pk)
    if action == 'start':
        current = FocusSession.objects.filter(owner=user).exclude(status='finished').first()
        if current:
            return current
        if minutes not in (15,25,45,60):
            raise ValueError('请选择 15、25、45 或 60 分钟。')
        task = get_object_or_404(Task.objects.select_for_update(),pk=task_id,course__owner=user,course__is_archived=False,status='todo') if task_id else None
        course = task.course if task else get_object_or_404(Course,pk=course_id,owner=user,is_archived=False) if course_id else None
        current = FocusSession.objects.create(owner=user,course=course,task=task,task_title=task.title if task else '',target_seconds=minutes*60,started_at=now)
        FocusInterval.objects.create(session=current,started_at=now)
        return current
    current = get_object_or_404(FocusSession,pk=session_id,owner=user)
    if current.status == 'finished':
        return current
    if action == 'complete':
        # A throttled or adjusted browser clock never authorizes early completion.
        if seconds(current,now) >= current.target_seconds:
            settle(current,now,finish=True)
    elif action in ('pause','finish'):
        settle(current,now,finish=action=='finish')
    elif action == 'resume' and current.status == 'paused':
        current.status='running';current.save(update_fields=['status'])
        FocusInterval.objects.create(session=current,started_at=now)
    elif action != 'resume':
        raise ValueError('无效操作。')
    return current


@login_required
@require_http_methods(['GET'])
def state(request):
    now=timezone.now()
    from .focus_history import time_buckets
    week=time_buckets(request.user,timezone.localdate()-timedelta(days=6),7,now)
    current=FocusSession.objects.filter(owner=request.user).exclude(status='finished').prefetch_related('intervals').first()
    response=JsonResponse({'session':current.pk if current else None,'status':current.status if current else None,
        'remaining':current.target_seconds-seconds(current,now) if current else 0,
        'today_minutes':week[-1]['minutes'],'week':week,
        'week_minutes':sum(row['microseconds'] for row in week)//60000000,'week_active_days':sum(row['microseconds']>0 for row in week)})
    response['Cache-Control']='no-store'
    return response


def daily_seconds(user, day, now=None):
    from .focus_history import time_buckets
    return time_buckets(user,day,1,now)[0]['seconds']


@login_required
@require_http_methods(['GET','POST'])
def workspace(request):
    for key in ('task','course'):
        value=request.GET.get(key)
        if value and (not value.isascii() or not value.isdecimal()):
            raise Http404('无效的学习对象。')
    if request.method == 'POST':
        try:
            result=command(request.user,request.POST.get('action'),request.POST.get('session'),request.POST.get('course'),int(request.POST.get('minutes',25)),task_id=request.POST.get('task'))
            if request.POST.get('action') in ('finish','complete') and result.status=='finished':
                messages.success(request,'本轮专注已保存。休息一会儿，再开始下一段学习。')
        except (ValueError,TypeError):
            messages.error(request,'无法执行操作，请检查选择后重试。')
        return redirect('focus')
    now=timezone.now()
    selected_task=get_object_or_404(Task,pk=request.GET['task'],course__owner=request.user,course__is_archived=False,status='todo') if request.GET.get('task') else None
    selected_course=selected_task.course if selected_task else get_object_or_404(Course,pk=request.GET['course'],owner=request.user,is_archived=False) if request.GET.get('course') else None
    active=FocusSession.objects.filter(owner=request.user).exclude(status='finished').prefetch_related('intervals').first()
    elapsed=seconds(active,now) if active else 0
    from django.core.paginator import Paginator
    from .focus_history import HistoryFilter, filtered_history, time_buckets
    history_form=HistoryFilter(request.GET,user=request.user)
    history_page=Paginator(filtered_history(request.user,history_form),12).get_page(request.GET.get('history_page'))
    history=list(history_page.object_list)
    week=time_buckets(request.user,timezone.localdate()-timedelta(days=6),7,now)
    peak=max([row['seconds'] for row in week]+[1])
    for row in week:row['bar_percent']=round(row['seconds']/peak*100,1)
    history_query=request.GET.copy();history_query.pop('history_page',None)
    for entry in history:
        elapsed_seconds=seconds(entry,now)
        entry.duration_label=f'{elapsed_seconds//60} 分 {elapsed_seconds%60:02d} 秒'
    from .focus_daily import daily_context
    day_context=daily_context(request,now)
    total=week[-1]['seconds']
    return render(request,'learning/focus.html',{**day_context,'history_form':history_form,'history_page':history_page,'history_query':history_query.urlencode(),'week':week,'week_minutes':sum(row['microseconds'] for row in week)//60000000,'week_active_days':sum(row['microseconds']>0 for row in week),'selected_task':selected_task,'selected_course':selected_course,'title':'专注学习','section':'focus','active':active,'remaining':active.target_seconds-elapsed if active else 1500,'focus_minutes':total//60,'history':history,'courses':Course.objects.filter(owner=request.user,is_archived=False)})

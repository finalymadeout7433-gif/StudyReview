"""Daily subject breakdown from the same capped intervals as focus totals."""
import calendar
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from .models import FocusSession
from .focus_history import effective_intervals

COLORS=['#376b58','#bf793d','#557db4','#9b6397','#bb5e65','#718344','#548b91','#82705c']

def duration(us):
    seconds=us//1000000
    if 0<us<1000000:return '不足1秒'
    hours,rest=divmod(seconds,3600);minutes,seconds=divmod(rest,60)
    return (f'{hours}小时' if hours else '')+f'{minutes}分{seconds:02d}秒'

def daily_breakdown(user,day,now=None):
    now=now or timezone.now()
    begin=timezone.make_aware(datetime.combine(day,time.min));end=begin+timedelta(days=1)
    sessions=FocusSession.objects.filter(owner=user,started_at__lt=end).filter(Q(ended_at__gte=begin)|Q(ended_at__isnull=True)).select_related('course').prefetch_related('intervals').order_by('-started_at','-pk')
    totals={};records=[]
    for session in sessions:
        us=0
        for start,stop in effective_intervals(session,now):
            overlap=min(stop,end)-max(start,begin)
            us+=max(0,overlap.days*86400000000+overlap.seconds*1000000+overlap.microseconds)
        if not us:continue
        key=session.course_id
        kind_label=('已归档课程' if session.course.is_archived else '课程专注') if key else '未关联课程'
        group=totals.setdefault(key,{'name':session.course.name if key else '自由专注','microseconds':0,'course_id':key,'kind_label':kind_label})
        group['microseconds']+=us
        records.append({'id':session.pk,'name':group['name'],'kind_label':kind_label,'task':session.task_title,'task_deleted':bool(session.task_title) and session.task_id is None,'started_at':session.started_at,'ended_at':session.ended_at,'status':session.get_status_display(),'duration':duration(us)})
    groups=sorted(totals.values(),key=lambda r:(-r['microseconds'],r['course_id'] or 0));total=sum(r['microseconds'] for r in groups)
    # Largest remainders: displayed percentages sum to exactly 100.0%.
    shares=[r['microseconds']*1000//total for r in groups] if total else []
    if total:
        order=sorted(range(len(groups)),key=lambda i:-(groups[i]['microseconds']*1000%total))
        for i in order[:1000-sum(shares)]:shares[i]+=1
    stops=[];cursor=0
    for i,row in enumerate(groups):
        row.update(number=i+1,duration=duration(row['microseconds']),percent=f'{shares[i]/10:.1f}')
        # Distinct adjacent categories even when course IDs share a palette slot.
        row['color']=COLORS[i] if i<len(COLORS) else f'hsl({i*137.508%360:.3f} 42% 42%)'
        angle=row['microseconds']/total*360
        stops.append(f"{row['color']} {cursor:.8f}deg {cursor+angle:.8f}deg");cursor+=angle
    return {'groups':groups,'records':records,'total_microseconds':total,'total_duration':duration(total),'gradient':'conic-gradient('+','.join(stops)+')' if stops else ''}

def daily_context(request,now):
    today=timezone.localdate(now);error=''
    try:
        day=date.fromisoformat(request.GET.get('day',today.isoformat()))
        if not 1900<=day.year<=2100:raise ValueError()
    except (ValueError,TypeError):day=today;error='日期无效，请从日历重新选择1900年至2100年之间的一天。'
    month=day.replace(day=1)
    if request.GET.get('month'):
        try:
            month=date.fromisoformat(request.GET['month']+'-01')
            if not 1900<=month.year<=2100:raise ValueError()
        except ValueError:
            month=day.replace(day=1)
            error='月份无效，请在日历中重新选择1900年至2100年之间的月份。'
    def link(d,**extra):return '?'+urlencode({'day':d.isoformat(),**extra})+'#focus-history'
    grid=[]
    for week in calendar.Calendar().monthdatescalendar(month.year,month.month):
        grid.append([{'day':d.day,'selected':d==day,'today':d==today,'outside':d.month!=month.month,'label':f'{d.year}年{d.month}月{d.day}日','url':link(d)} for d in week])
    prev_month=(month-timedelta(days=1)).replace(day=1);next_month=(month+timedelta(days=32)).replace(day=1)
    data=daily_breakdown(request.user,day,now) if not error else {'groups':[],'records':[],'total_microseconds':0,'total_duration':'0分00秒','gradient':''}
    page=Paginator(data['records'],12).get_page(request.GET.get('day_page'))
    return {'daily':data,'daily_page':page,'day':day,'day_error':error,'calendar_weeks':grid,'calendar_month':month,'calendar_open':bool(request.GET.get('month')) or bool(error),'previous_month':link(day,month=prev_month.strftime('%Y-%m')) if prev_month.year>=1900 else None,'next_month':link(day,month=next_month.strftime('%Y-%m')) if next_month.year<=2100 else None,'previous_day':link(day-timedelta(days=1)) if day>date(1900,1,1) else None,'next_day':link(day+timedelta(days=1)) if day<date(2100,12,31) else None,'today_url':link(today),'daily_query':urlencode({'day':day.isoformat()})}

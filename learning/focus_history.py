from datetime import datetime, time, timedelta
from django import forms
from django.db.models import Q
from django.utils import timezone
from .models import Course, FocusSession

class HistoryFilter(forms.Form):
    history_course=forms.ChoiceField(label='课程',required=False)
    history_start=forms.DateField(label='开始日期从',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    history_end=forms.DateField(label='开始日期至',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['history_course'].choices=[('','全部课程'),('free','自由专注')]+[(str(c.pk),c.name+('（已归档）' if c.is_archived else '')) for c in Course.objects.filter(owner=user)]
    def clean(self):
        data=super().clean()
        for key in ('history_start','history_end'):
            if data.get(key) and data[key].year>9998:
                self.add_error(key,'日期超出支持范围。')
        if data.get('history_start') and data.get('history_end') and data['history_start']>data['history_end']:
            self.add_error('history_end','结束日期不能早于开始日期。')
        return data

def effective_intervals(session, now):
    """Ordered actual intervals, capped once per session, shared by all reports."""
    remaining=session.target_seconds
    for interval in session.intervals.all():
        stop=min(interval.ended_at or now,interval.started_at+timedelta(seconds=remaining))
        duration=max(0,(stop-interval.started_at).total_seconds())
        yield interval.started_at,stop
        remaining=max(0,remaining-duration)


def course_seconds(user, course_ids, first_day, last_day, now=None):
    """Actual overlap with the selected local date range; free focus is separate."""
    from collections import defaultdict
    now=now or timezone.now()
    begin=timezone.make_aware(datetime.combine(first_day,time.min))
    finish=timezone.make_aware(datetime.combine(last_day+timedelta(days=1),time.min))
    sessions=FocusSession.objects.filter(owner=user,course_id__in=course_ids,started_at__lt=finish).filter(Q(ended_at__gte=begin)|Q(ended_at__isnull=True)).prefetch_related('intervals')
    totals=defaultdict(float)
    for session in sessions:
        for start,stop in effective_intervals(session,now):
            totals[session.course_id]+=max(0,(min(stop,finish)-max(start,begin)).total_seconds())
    return {key:int(value) for key,value in totals.items()}


def time_buckets(user, first_day, days, now=None):
    """Split capped effective intervals at local midnight, in two ORM queries."""
    now=now or timezone.now()
    boundaries=[timezone.make_aware(datetime.combine(first_day+timedelta(days=i),time.min)) for i in range(days+1)]
    totals=[0.0]*days
    sessions=FocusSession.objects.filter(owner=user,started_at__lt=boundaries[-1]).filter(Q(ended_at__gte=boundaries[0])|Q(ended_at__isnull=True)).prefetch_related('intervals')
    for session in sessions:
        for start,stop in effective_intervals(session,now):
            for i in range(days):
                totals[i]+=max(0,(min(stop,boundaries[i+1])-max(start,boundaries[i])).total_seconds())
    return [{'day':first_day+timedelta(days=i),'seconds':int(value),'microseconds':round(value*1000000),'minutes':int(value)//60,'label':f'{int(value)//60}分{int(value)%60:02d}秒'} for i,value in enumerate(totals)]

def filtered_history(user,form):
    records=FocusSession.objects.filter(owner=user,status='finished').select_related('course').prefetch_related('intervals')
    if not form.is_valid():return records.none()
    data=form.cleaned_data
    course=data.get('history_course')
    if course=='free':records=records.filter(course__isnull=True)
    elif course:records=records.filter(course_id=course)
    if data.get('history_start'):
        start=timezone.make_aware(datetime.combine(data['history_start'],time.min))
        records=records.filter(started_at__gte=start)
    if data.get('history_end'):
        end=timezone.make_aware(datetime.combine(data['history_end']+timedelta(days=1),time.min))
        records=records.filter(started_at__lt=end)
    return records

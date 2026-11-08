"""Read-only, bulk-aggregated course activity. Counts never multiply across joins."""
from django.db.models import Count,Q
from django.utils import timezone
from .models import Course,Task,WrongQuestion,ReviewRecord
from .services import date_interval
from .focus_history import course_seconds

def course_activity(user,course_id,start,end,review_source='all'):
    courses=Course.objects.filter(owner=user,is_archived=False)
    if course_id:courses=courses.filter(pk=course_id)
    courses=list(courses.annotate(chapter_count=Count('chapters',distinct=True),point_count=Count('knowledge_points',distinct=True)))
    ids=[c.pk for c in courses]
    if not ids:return []
    today=timezone.localdate()
    tasks={r['course_id']:r for r in Task.objects.filter(course_id__in=ids).order_by().values('course_id').annotate(total=Count('pk'),done=Count('pk',filter=Q(status='done')))}
    questions={r['course_id']:r for r in WrongQuestion.objects.filter(course_id__in=ids,is_archived=False).order_by().values('course_id').annotate(total=Count('pk'),due=Count('pk',filter=Q(next_review_date__lte=today)))}
    begin,finish=date_interval(start,end)
    reviews=ReviewRecord.objects.filter(question__course_id__in=ids,question__is_archived=False,reviewed_at__gte=begin,reviewed_at__lt=finish)
    if review_source in ('personal','example'):reviews=reviews.filter(is_example=review_source=='example')
    reviews=dict(reviews.order_by().values('question__course_id').annotate(total=Count('pk')).values_list('question__course_id','total'))
    focus=course_seconds(user,ids,start,end)
    result=[]
    for course in courses:
        seconds=focus.get(course.pk,0);task=tasks.get(course.pk,{});question=questions.get(course.pk,{})
        result.append({'course':course,'tasks_total':task.get('total',0),'tasks_done':task.get('done',0),'questions_total':question.get('total',0),'due':question.get('due',0),'reviews':reviews.get(course.pk,0),'focus_seconds':seconds,'focus_label':f'{seconds//60}分{seconds%60:02d}秒'})
    return result

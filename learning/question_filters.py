"""Owner-scoped curriculum drill-down and review status filters."""
from django.db.models import Count,Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from .models import Chapter,KnowledgePoint

def filtered_questions(user,params,questions,course,archive):
    notice='';chapter=point=None;chapter_ids=None
    def owned(model,key):
        value=params.get(key)
        if not value:return None
        if not value.isascii() or not value.isdecimal():raise Http404()
        return get_object_or_404(model.objects.select_related('course'),pk=value,course__owner=user)
    chapter=owned(Chapter,'chapter');point=owned(KnowledgePoint,'point')
    if chapter and course and chapter.course_id!=course.pk:
        chapter=None;notice='课程已改变，已清除不属于该课程的章节筛选。'
    if chapter:
        course=course or chapter.course
        chapter_ids=list(Chapter.objects.filter(Q(pk=chapter.pk)|Q(parent_id=chapter.pk),course=course).values_list('pk',flat=True))
    if point and ((course and point.course_id!=course.pk) or (chapter_ids is not None and point.chapter_id not in chapter_ids)):
        point=None;notice='学习范围已改变，已清除范围外的知识点筛选。'
    if course:questions=questions.filter(course=course)
    if chapter_ids is not None:questions=questions.filter(knowledge_points__chapter_id__in=chapter_ids)
    if point:questions=questions.filter(knowledge_points=point)
    search=params.get('q','').strip()[:180]
    if search:questions=questions.filter(title__icontains=search)
    questions=questions.distinct()
    active=Q(is_archived=False,course__is_archived=False)
    due=active & Q(next_review_date__lte=timezone.localdate())
    scheduled=active & Q(next_review_date__gt=timezone.localdate())
    counts=questions.aggregate(all_count=Count('pk',distinct=True),due_count=Count('pk',filter=due,distinct=True),scheduled_count=Count('pk',filter=scheduled,distinct=True))
    status=params.get('review_status','all')
    if status not in ('all','due','scheduled'):status='all'
    if status=='due':questions=questions.filter(due)
    elif status=='scheduled':questions=questions.filter(scheduled)
    query=params.copy();query.pop('page',None)
    for key,value in [('course',course),('chapter',chapter),('point',point)]:
        if value:query[key]=str(value.pk)
        else:query.pop(key,None)
    query['archive']=archive;query['q']=search
    tabs=[]
    for key,label in [('all','全部'),('due','待复习'),('scheduled','已安排')]:
        query['review_status']=key
        tabs.append({'key':key,'label':label,'count':counts[key+'_count'],'url':reverse('question-list')+'?'+query.urlencode()})
    points=KnowledgePoint.objects.filter(course__owner=user).select_related('course')
    chapters=Chapter.objects.filter(course__owner=user).select_related('course','parent')
    if course:points=points.filter(course=course);chapters=chapters.filter(course=course)
    if chapter_ids is not None:points=points.filter(chapter_id__in=chapter_ids)
    return questions,{'selected_course':course,'selected_chapter':chapter,'selected_point':point,'points':points,'chapters':chapters,'review_status':status,'review_tabs':tabs,'filter_notice':notice,'q':search,'archive':archive}

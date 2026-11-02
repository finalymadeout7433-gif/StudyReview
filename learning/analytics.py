"""Read-only chart data with the same owner/archive/date scope as statistics."""
from collections import Counter
from datetime import timedelta
from math import ceil
from zoneinfo import ZoneInfo

from django.db.models import Count, Q
from django.utils import timezone

from .models import Course, KnowledgePoint, ReviewRecord, WrongQuestion
from .services import date_interval


def learning_analytics(user, course_id, start, end, review_source='all'):
    today = timezone.localdate()
    courses = Course.objects.filter(owner=user, is_archived=False)
    if course_id:
        courses = courses.filter(pk=course_id)
    questions = WrongQuestion.objects.filter(course__in=courses, is_archived=False)
    begin, finish = date_interval(start, end)
    reviews = ReviewRecord.objects.filter(question__in=questions, reviewed_at__gte=begin, reviewed_at__lt=finish)
    if review_source in ('personal', 'example'):
        reviews = reviews.filter(is_example=review_source == 'example')
    daily, ratings = Counter(), Counter()
    course_ratings, example_count = Counter(), 0
    # Use timezone-aware Python conversion; no MySQL timezone tables are needed.
    for stamp, rating, course_id_value, example in reviews.order_by().values_list(
            'reviewed_at', 'rating', 'question__course_id', 'is_example').iterator(chunk_size=1000):
        daily[stamp.astimezone(ZoneInfo('Asia/Shanghai')).date()] += 1
        ratings[rating] += 1
        course_ratings[(course_id_value, rating)] += 1
        example_count += int(example)
    span = (end-start).days+1
    bucket_days = max(1, ceil(span/30))
    trend = []
    for offset in range(0, span, bucket_days):
        first = start+timedelta(days=offset)
        last = min(end, first+timedelta(days=bucket_days-1))
        trend.append({'date': first.isoformat(), 'end': last.isoformat(), 'label': first.strftime('%m/%d'),
                      'count': sum(daily[first+timedelta(days=n)] for n in range((last-first).days+1))})
    course_rows = courses.annotate(total=Count('tasks', distinct=True),
        done=Count('tasks', filter=Q(tasks__status='done'), distinct=True),
        overdue=Count('tasks', filter=Q(tasks__status='todo', tasks__due_date__lt=today), distinct=True),
    ).order_by('-total', 'pk')[:8]
    progress = [{'id': c.pk, 'name': c.name, 'done': c.done, 'overdue': c.overdue,
                 'pending': c.total-c.done-c.overdue, 'total': c.total} for c in course_rows]
    points = KnowledgePoint.objects.filter(course__in=courses).annotate(
        count=Count('questions', filter=Q(questions__in=questions), distinct=True)
    ).filter(count__gt=0).order_by('-count', 'pk')[:8]
    upcoming_counts = dict(questions.filter(next_review_date__gte=today,
        next_review_date__lt=today+timedelta(days=7)).values('next_review_date')
        .annotate(count=Count('pk')).values_list('next_review_date', 'count'))
    upcoming = [{'date': (today+timedelta(days=n)).isoformat(),
                 'label': '今天' if n == 0 else (today+timedelta(days=n)).strftime('%m/%d'),
                 'count': upcoming_counts.get(today+timedelta(days=n), 0)} for n in range(7)]
    heat_start = max(start, end-timedelta(days=83))
    heatmap = [{'date': (heat_start+timedelta(days=n)).isoformat(),
                'count': daily[heat_start+timedelta(days=n)]} for n in range((end-heat_start).days+1)]
    from .insights import extended_insights
    extended = extended_insights(user, courses, questions, review_source)
    matrix = [{'id': c['id'], 'name': c['name'], 'counts': [course_ratings[(c['id'],k)]
        for k in ('again','hard','good')]} for c in courses.order_by('pk').values('id','name')[:12]]
    return {**extended, 'review_source': review_source, 'example_reviews': example_count,
            'rating_matrix': matrix, 'trend': trend, 'bucket_days': bucket_days, 'review_total': sum(daily.values()),
            'active_days': len(daily), 'courses': progress,
            'points': [{'id': p.pk, 'name': p.name, 'count': p.count} for p in points],
            'ratings': [{'key': k, 'name': label, 'count': ratings[k]} for k, label in
                        [('again', '需再练习'), ('hard', '独立作答较费力'), ('good', '独立作答较熟练')]],
            'upcoming': upcoming, 'overdue_questions': questions.filter(next_review_date__lt=today).count(),
            'heatmap': heatmap, 'heatmap_start': heat_start.isoformat(), 'heatmap_end': end.isoformat()}

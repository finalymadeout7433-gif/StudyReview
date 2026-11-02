"""Bounded, read-only projections and instance relationships for the statistics UI."""
from datetime import timedelta, timezone as utc

from django.core.exceptions import ValidationError
from django.db.models import Count, Exists, OuterRef
from django.utils import timezone

from learning.models import KnowledgePoint, ReviewRecord, Task
from scheduling.engine import make_scheduler, validate_card_state, validate_metadata
from scheduling.models import SchedulingState


def extended_insights(user, courses, questions, review_source='all'):
    today, now = timezone.localdate(), timezone.now().astimezone(utc.utc)
    rows = list(courses.order_by('pk').values('id', 'name'))
    finish = today+timedelta(days=14)
    task_counts = {(r['course_id'], r['due_date']): r['count'] for r in Task.objects.filter(
        course__in=courses, status='todo', due_date__gte=today, due_date__lt=finish)
        .values('course_id','due_date').annotate(count=Count('pk'))}
    question_counts = {(r['course_id'], r['next_review_date']): r['count'] for r in questions.filter(
        next_review_date__gte=today, next_review_date__lt=finish)
        .values('course_id','next_review_date').annotate(count=Count('pk'))}
    days = [{'date': (today+timedelta(days=n)).isoformat(),
             'label': '今天' if n==0 else (today+timedelta(days=n)).strftime('%m/%d')} for n in range(14)]
    workload = [{'id': c['id'], 'name': c['name'], 'days': [
        {'tasks': task_counts.get((c['id'], today+timedelta(days=n)),0),
         'questions': question_counts.get((c['id'], today+timedelta(days=n)),0)} for n in range(14)]} for c in rows[:12]]

    # Source flags are stored on immutable review rows, not inferred from titles.
    example_history = ReviewRecord.objects.filter(question_id=OuterRef('question_id'), is_example=True)
    states = SchedulingState.objects.filter(user=user, question__in=questions).select_related(
        'question','question__course').annotate(has_examples=Exists(example_history)).order_by('question__next_review_date','pk')
    scheduler = make_scheduler()
    from fsrs import Card
    risks = {'stable': 0, 'attention': 0, 'priority': 0, 'unknown': 0}
    projections, valid, invalid, hidden = [], 0, 0, 0
    for state in states:
        if (review_source=='personal' and state.has_examples) or (review_source=='example' and not state.has_examples):
            hidden += 1
            continue
        try:
            validate_metadata(state.algorithm,state.algorithm_version,state.config_version,state.config_snapshot)
            payload = validate_card_state(state.card_state,state.question_id)
            if payload['last_review'] is None:
                continue
            card = Card.from_dict(payload)
            if card.last_review > now:
                raise ValidationError('Future review state')
            probability = scheduler.get_card_retrievability(card, current_datetime=now)
            valid += 1
            risks['stable' if probability>=.9 else 'attention' if probability>=.7 else 'priority'] += 1
            if len(projections)<24:
                projections.append({'id': state.question_id, 'title': state.question.title,
                    'course': state.question.course.name, 'example': bool(state.has_examples),
                    'stability': round(card.stability,2), 'difficulty': round(card.difficulty,2),
                    'current': round(probability*100,1), 'due_date': state.question.next_review_date.isoformat(),
                    'last_review': card.last_review.isoformat(),
                    'points': [{'day': n, 'value': round(scheduler.get_card_retrievability(
                        card,current_datetime=now+timedelta(days=n))*100,2)} for n in range(31)]})
        except (ValidationError, ValueError, TypeError, KeyError, OverflowError):
            invalid += 1
    risks['unknown'] = questions.count()-valid

    graph = []
    for c in rows[:8]:
        points = list(KnowledgePoint.objects.filter(course_id=c['id']).order_by('pk').values('id','name')[:9])
        selected_points = points[:8]
        point_ids = {p['id'] for p in selected_points}
        selected_questions = list(questions.filter(course_id=c['id']).prefetch_related('knowledge_points')
            .order_by('next_review_date','pk')[:11])
        graph.append({'id': c['id'], 'name': c['name'], 'points': selected_points,
            'questions': [{'id': q.pk, 'title': q.title,
                'point_ids': [p.pk for p in q.knowledge_points.all() if p.pk in point_ids]} for q in selected_questions[:10]],
            'truncated': len(points)>8 or len(selected_questions)>10})
    return {'memory': {'cards': projections, 'valid_count': valid, 'invalid_count': invalid,
        'priority_cards': sorted(projections, key=lambda item: (item['current'],item['id']))[:5],
        'hidden_count': hidden, 'risks': risks, 'target': 90, 'prediction_date': now.isoformat()},
        'workload': {'dates': days, 'courses': workload, 'truncated': len(rows)>12},
        'relationships': graph, 'examples_all': ReviewRecord.objects.filter(question__in=questions,is_example=True).count()}

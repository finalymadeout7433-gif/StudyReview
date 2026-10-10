"""All user writes enter here. Lock order: course first, then child object.

This serializes archive, edits and review writes for a course. Forms improve UX;
these checks remain necessary when callers bypass forms or requests race.
"""
import uuid
import hashlib
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.utils import timezone
from .models import Course, KnowledgePoint, Task, WrongQuestion, QuestionKnowledgePoint, ReviewRecord
from attachments.models import ImageRole
from attachments.services import sync_question_images, snapshot_question_images
from scheduling.models import SchedulingState
from scheduling.services import prepare_schedule, commit_schedule

RATING_DAYS = {'again': 1, 'hard': 3, 'good': 7}
TOKEN_SALT = 'study-review-submission-v1'
MIN_STAT_DATE = date(1900, 1, 1)
MAX_STAT_DATE = date(2100, 12, 31)


def review_version(question):
    """Include course/point labels too, so every saved snapshot matches the viewed version."""
    values = [question.updated_at.isoformat(), question.course.name,
        list(question.knowledge_points.order_by('pk').values_list('pk', 'name')),
        list(question.image_links.order_by('role', 'position').values_list('role', 'position', 'attachment_id')),
        SchedulingState.objects.filter(question=question, user_id=question.course.owner_id).values_list('revision', flat=True).first()]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()


def make_token(user, operation, obj=None):
    payload = {'user': user.pk, 'op': operation, 'key': str(uuid.uuid4())}
    if obj is not None:
        payload.update({'object': obj.pk, 'version': review_version(obj)})
    return signing.dumps(payload, salt=TOKEN_SALT, compress=True)


def read_token(token, user, operation, object_id=None, revealed=False):
    try:
        payload = signing.loads(token, salt=TOKEN_SALT, max_age=86400)
        if payload['user'] != user.pk or payload['op'] != operation:
            raise ValueError()
        if object_id is not None and payload.get('object') != object_id:
            raise ValueError()
        if revealed and not payload.get('revealed'):
            raise ValueError()
        uuid.UUID(payload['key'])
        return payload
    except (signing.BadSignature, ValueError, KeyError, TypeError):
        raise ValidationError('提交标识无效或已过期，请重新打开页面。')


def reveal_token(token, user, question):
    payload = read_token(token, user, 'review', question.pk)
    if payload.get('version') != review_version(question):
        raise ValidationError('题目已发生变化，请重新进入复习以查看最新内容。')
    payload['revealed'] = True
    return signing.dumps(payload, salt=TOKEN_SALT, compress=True)


def owned_course(user, pk, lock=False, writable=False):
    queryset = Course.objects.filter(owner=user)
    if lock:
        queryset = queryset.select_for_update()
    try:
        course = queryset.get(pk=pk)
    except Course.DoesNotExist:
        raise Http404('未找到该内容。')
    if writable and course.is_archived:
        raise ValidationError('课程已归档，内容只读。请先恢复课程。')
    return course


@transaction.atomic
def save_course(user, values, pk=None):
    course = owned_course(user, pk, lock=True, writable=True) if pk else Course(owner=user)
    course.name = values['name'].strip()
    course.description = values.get('description', '').strip()
    course.full_clean()
    course.save()
    return course


@transaction.atomic
def archive_course(user, pk, archived):
    course = owned_course(user, pk, lock=True)
    course.is_archived = archived
    course.save(update_fields=['is_archived'])
    return course


@transaction.atomic
def save_point(user, course_id, values, pk=None):
    course = owned_course(user, course_id, lock=True, writable=True)
    if pk:
        try:
            point = KnowledgePoint.objects.select_for_update().get(pk=pk, course=course)
        except KnowledgePoint.DoesNotExist:
            raise Http404()
    else:
        point = KnowledgePoint(course=course)
    point.name = values['name'].strip()
    point.full_clean()
    point.save()
    return point


@transaction.atomic
def delete_point(user, course_id, pk):
    course = owned_course(user, course_id, lock=True, writable=True)
    try:
        point = KnowledgePoint.objects.select_for_update().get(course=course, pk=pk)
    except KnowledgePoint.DoesNotExist:
        raise Http404()
    if point.question_links.exists():
        raise ValidationError('此知识点已被错题引用，请先在错题编辑页解除关联。')
    point.delete()


@transaction.atomic
def save_task(user, values, pk=None, token=None):
    course_id = values['course'].pk
    course = owned_course(user, course_id, lock=True, writable=True)
    if pk:
        try:
            task = Task.objects.select_for_update().get(pk=pk, course=course)
        except Task.DoesNotExist:
            raise Http404()
    else:
        payload = read_token(token, user, 'task-create')
        existing = Task.objects.filter(creation_key=payload['key']).first()
        if existing:
            if existing.course.owner_id != user.pk:
                raise Http404()
            return existing
        task = Task(course=course, creation_key=payload['key'])
    for field in ('title', 'description', 'due_date'):
        setattr(task, field, values.get(field, ''))
    task.full_clean()
    task.save()
    return task


def lock_task(user, pk):
    try:
        course_id = Task.objects.filter(course__owner=user).values_list('course_id', flat=True).get(pk=pk)
    except Task.DoesNotExist:
        raise Http404()
    course = owned_course(user, course_id, lock=True, writable=True)
    try:
        return Task.objects.select_for_update().get(pk=pk, course=course)
    except Task.DoesNotExist:
        raise Http404()


@transaction.atomic
def set_task_status(user, pk, done):
    task = lock_task(user, pk)
    if done and task.status == Task.Status.TODO:
        task.status, task.completed_at = Task.Status.DONE, timezone.now()
    elif not done and task.status == Task.Status.DONE:
        task.status, task.completed_at = Task.Status.TODO, None
    task.full_clean()
    task.save(update_fields=['status', 'completed_at'])
    return task


@transaction.atomic
def delete_task(user, pk):
    lock_task(user, pk).delete()


def checked_points(course, points):
    ids = [point.pk if isinstance(point, KnowledgePoint) else point for point in points]
    found = list(KnowledgePoint.objects.filter(pk__in=ids, course=course))
    if len(found) != len(set(ids)):
        raise ValidationError({'knowledge_points': '只能关联本课程的知识点。'})
    return found


@transaction.atomic
def save_question(user, values, pk=None, token=None):
    course = owned_course(user, values['course'].pk, lock=True, writable=True)
    if pk:
        try:
            question = WrongQuestion.objects.select_for_update().get(pk=pk, course=course)
        except WrongQuestion.DoesNotExist:
            raise Http404()
        if question.is_archived:
            raise ValidationError('错题已归档，请先恢复后再编辑。')
    else:
        payload = read_token(token, user, 'question-create')
        existing = WrongQuestion.objects.filter(creation_key=payload['key']).first()
        if existing:
            if existing.course.owner_id != user.pk:
                raise Http404()
            return existing
        question = WrongQuestion(course=course, creation_key=payload['key'])
    points = checked_points(course, values.get('knowledge_points', []))
    next_date = values['next_review_date']
    # An existing overdue schedule may stay unchanged; newly chosen dates cannot be past.
    if next_date < timezone.localdate() and (not pk or next_date != question.next_review_date):
        raise ValidationError({'next_review_date': '请选择今天或未来的日期。'})
    for field in ('title', 'content', 'original_answer', 'correct_answer', 'error_reason', 'next_review_date'):
        setattr(question, field, values[field])
    question.full_clean()
    question.save()
    question.point_links.all().delete()
    for point in points:
        QuestionKnowledgePoint.objects.create(question=question, knowledge_point=point)
    if 'image_groups' in values:
        groups = values['image_groups']
        if not isinstance(groups, dict) or set(groups) - set(ImageRole.values):
            raise ValidationError({'image_payload': '图片分组无效，请重新选择。'})
        for role in ImageRole.values:
            sync_question_images(user, question, groups.get(role, []), role=role)
    return question


@transaction.atomic
def archive_question(user, pk, archived):
    try:
        course_id = WrongQuestion.objects.filter(course__owner=user).values_list('course_id', flat=True).get(pk=pk)
    except WrongQuestion.DoesNotExist:
        raise Http404()
    course = owned_course(user, course_id, lock=True, writable=True)
    question = WrongQuestion.objects.select_for_update().get(pk=pk, course=course)
    question.is_archived = archived
    question.save(update_fields=['is_archived', 'updated_at'])
    return question


@transaction.atomic
def submit_review(user, question_id, values, token):
    payload = read_token(token, user, 'review', question_id, revealed=True)
    try:
        course_id = WrongQuestion.objects.filter(course__owner=user).values_list('course_id', flat=True).get(pk=question_id)
    except WrongQuestion.DoesNotExist:
        raise Http404()
    course = owned_course(user, course_id, lock=True)
    question = WrongQuestion.objects.select_for_update().get(pk=question_id, course=course)
    existing = ReviewRecord.objects.filter(submission_key=payload['key']).first()
    if existing:
        if existing.question_id != question_id:
            raise ValidationError('提交标识不匹配。')
        return existing, False
    if question.is_archived or course.is_archived:
        raise ValidationError('已归档内容不能提交复习。')
    if payload.get('version') != review_version(question):
        raise ValidationError('题目或复习安排已发生变化，请重新进入复习。')
    reviewed_at = timezone.now()
    today = reviewed_at.astimezone(ZoneInfo('Asia/Shanghai')).date()
    if question.next_review_date > today:
        raise ValidationError('这道题尚未到复习日期。')
    answer = values.get('answer', '').strip()
    rating = values.get('rating')
    if not answer or len(answer) > 20000:
        raise ValidationError({'answer': '请填写本次作答，最多 20000 字；不会时可写“未作答”。'})
    if rating not in RATING_DAYS:
        raise ValidationError({'rating': '请选择自评。'})
    override_date = values.get('next_review_date')
    if override_date is not None and type(override_date) is not date:
        raise ValidationError({'next_review_date': '请选择有效的未来日期。'})
    proposal = prepare_schedule(user, question, rating, reviewed_at)
    next_date = override_date if override_date is not None else proposal.due_date
    if next_date <= today:
        raise ValidationError({'next_review_date': '下次复习必须晚于今天。'})
    record = ReviewRecord(
        question=question, reviewed_at=reviewed_at, review_date=today, answer=answer, rating=rating,
        note=values.get('note', '').strip(), next_review_date=next_date,
        title_snapshot=question.title, question_snapshot=question.content,
        original_answer_snapshot=question.original_answer, correct_answer_snapshot=question.correct_answer,
        error_reason_snapshot=question.error_reason, course_snapshot=course.name,
        knowledge_points_snapshot=list(question.knowledge_points.values_list('name', flat=True)),
        submission_key=payload['key'],
    )
    record.full_clean()
    record.save()
    snapshot_question_images(question, record)
    commit_schedule(proposal, record, user_override_date=override_date)
    question.next_review_date = next_date
    question.save(update_fields=['next_review_date', 'updated_at'])
    return record, True


def date_interval(start, end):
    """Shanghai dates -> UTC half-open interval; no MySQL timezone tables needed."""
    errors = {}
    if type(start) is not date or not MIN_STAT_DATE <= start <= MAX_STAT_DATE:
        errors['start'] = '统计日期支持 1900-01-01 至 2100-12-31。'
    if type(end) is not date or not MIN_STAT_DATE <= end <= MAX_STAT_DATE:
        errors['end'] = '统计日期支持 1900-01-01 至 2100-12-31。'
    if errors:
        raise ValidationError(errors)
    if start > end:
        raise ValidationError({'end': '结束日期不能早于开始日期。'})
    zone = ZoneInfo('Asia/Shanghai')
    begin = datetime.combine(start, time.min, tzinfo=zone).astimezone(ZoneInfo('UTC'))
    finish = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone).astimezone(ZoneInfo('UTC'))
    return begin, finish


def summary(user, course_id=None, start=None, end=None):
    today = timezone.localdate()
    start, end = start or today - timedelta(days=6), end or today
    courses = Course.objects.filter(owner=user, is_archived=False)
    if course_id:
        courses = courses.filter(pk=course_id)
    tasks = Task.objects.filter(course__in=courses)
    questions = WrongQuestion.objects.filter(course__in=courses, is_archived=False)
    begin, finish = date_interval(start, end)
    reviews = ReviewRecord.objects.filter(question__in=questions, reviewed_at__gte=begin, reviewed_at__lt=finish)
    counts = tasks.aggregate(total=Count('pk'), done=Count('pk', filter=Q(status=Task.Status.DONE)),
        overdue=Count('pk', filter=Q(status=Task.Status.TODO, due_date__lt=today)))
    rating_counts = dict(reviews.values('rating').annotate(total=Count('pk')).values_list('rating', 'total'))
    review_total = sum(rating_counts.values())
    ratings = [{'label': label, 'key': key, 'count': rating_counts.get(key, 0),
        'percent': round(rating_counts.get(key, 0) / review_total * 100, 1) if review_total else 0}
        for key, label in ReviewRecord.Rating.choices]
    return {'courses_count': courses.count(), 'tasks_total': counts['total'], 'tasks_done': counts['done'],
        'tasks_pending': counts['total'] - counts['done'], 'overdue': counts['overdue'],
        'completion_rate': round(counts['done'] / counts['total'] * 100, 1) if counts['total'] else None,
        'questions_count': questions.count(), 'due_count': questions.filter(next_review_date__lte=today).count(),
        'review_total': review_total, 'ratings': ratings, 'start': start, 'end': end,
        'course_rows': courses.annotate(task_total=Count('tasks', distinct=True),
            task_done=Count('tasks', filter=Q(tasks__status='done'), distinct=True),
            question_total=Count('questions', filter=Q(questions__is_archived=False), distinct=True))}

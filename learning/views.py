from datetime import timedelta
import json
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from . import services
from .forms import (LoginForm, RegisterForm, CourseForm, PointForm, TaskForm,
    QuestionForm, AnswerForm, ReviewForm, StatisticsForm)
from .models import Course, KnowledgePoint, Task, WrongQuestion
from attachments.models import Attachment
from scheduling.services import suggest_schedule


def image_data(attachment, role='question'):
    from django.urls import reverse
    return {'id': str(attachment.pk), 'name': attachment.display_name, 'role': role,
        'width': attachment.width, 'height': attachment.height,
        'url': reverse('attachments:media', args=[attachment.pk]),
        'thumbnail_url': reverse('attachments:thumbnail', args=[attachment.pk])}


def question_images(question):
    return [image_data(link.attachment, link.role)
            for link in question.image_links.select_related('attachment').all()] if question else []


def form_images(user, form, question):
    if not form.is_bound:
        return question_images(question)
    try:
        rows = json.loads(form.data.get('image_payload') or '[]')
        if not isinstance(rows, list) or len(rows) > 24:
            return []
        result = []
        for row in rows:
            if not isinstance(row, dict) or row.get('role') not in ('question','original_answer','correct_answer','error_reason'):
                continue
            image = Attachment.objects.filter(pk=row.get('id'), owner=user).first()
            if image:
                result.append(image_data(image, row['role']))
        return result
    except (ValueError, TypeError, ValidationError):
        return []


class StudyLoginView(LoginView):
    template_name = 'registration/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True


class StudyLogoutView(LogoutView):
    http_method_names = ['post', 'options']


def form_error(form, error):
    if hasattr(error, 'message_dict'):
        for field, errors in error.message_dict.items():
            form.add_error(field if field in form.fields else None, errors)
    elif isinstance(error, ValidationError):
        form.add_error(None, error.messages)
    else:
        form.add_error(None, '内容发生冲突或已有同名记录，请检查输入后重试。')


def page(request, queryset):
    return Paginator(queryset, 20).get_page(request.GET.get('page'))


def archive_filter(request, queryset, question=False):
    selected = request.GET.get('archive', 'active')
    if selected not in ('active', 'archived', 'all'):
        selected = 'active'
    if question:
        archived = Q(is_archived=True) | Q(course__is_archived=True)
        if selected == 'active':
            queryset = queryset.filter(is_archived=False, course__is_archived=False)
        elif selected == 'archived':
            queryset = queryset.filter(archived)
    else:
        path = 'is_archived' if queryset.model is Course else 'course__is_archived'
        if selected != 'all':
            queryset = queryset.filter(**{path: selected == 'archived'})
    return queryset, selected


def selected_course(request):
    value = request.GET.get('course')
    if not value:
        return None
    try:
        pk = int(value)
    except (ValueError, TypeError):
        raise Http404()
    return services.owned_course(request.user, pk)


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
        except IntegrityError as exc:
            form_error(form, exc)
        else:
            login(request, user)
            messages.success(request, '注册成功。先创建一门课程，开始安排学习吧。')
            return redirect('course-create')
    return render(request, 'registration/register.html', {'form': form})


@login_required
def dashboard(request):
    stats = services.summary(request.user)
    tasks = Task.objects.filter(course__owner=request.user, course__is_archived=False, status='todo').select_related('course')[:6]
    questions = due_questions(request.user)[:6]
    return render(request, 'learning/dashboard.html', {'stats': stats, 'tasks': tasks, 'questions': questions,
        'section': 'overview', 'title': '学习概览'})


@login_required
def course_list(request):
    courses, selected = archive_filter(request, Course.objects.filter(owner=request.user))
    return render(request, 'learning/course_list.html', {'page_obj': page(request, courses),
        'archive': selected, 'section': 'courses', 'title': '课程与知识点'})


@login_required
def course_detail(request, pk):
    course = services.owned_course(request.user, pk)
    return render(request, 'learning/course_detail.html', {'course': course,
        'points': course.knowledge_points.all(), 'section': 'courses', 'title': course.name})


@login_required
def course_edit(request, pk=None):
    course = services.owned_course(request.user, pk) if pk else None
    if course and course.is_archived:
        return forbidden(request)
    form = CourseForm(request.POST or None, user=request.user, instance=course)
    if request.method == 'POST' and form.is_valid():
        try:
            course = services.save_course(request.user, form.cleaned_data, pk)
        except (ValidationError, IntegrityError) as exc:
            form_error(form, exc)
        else:
            messages.success(request, '课程已保存。')
            return redirect('course-detail', pk=course.pk)
    return render(request, 'learning/form.html', {'form': form, 'title': '编辑课程' if pk else '新建课程',
        'section': 'courses', 'cancel_url': course.get_absolute_url() if hasattr(course, 'get_absolute_url') else '/courses/'})


@login_required
@require_POST
def course_archive(request, pk):
    action = request.POST.get('action')
    if action not in ('archive', 'restore'):
        raise Http404()
    services.archive_course(request.user, pk, action == 'archive')
    messages.success(request, '课程已归档，历史保留且内容只读。' if action == 'archive' else '课程已恢复，原复习日期保持不变。')
    return redirect('course-detail', pk=pk)


@login_required
def point_edit(request, course_pk, pk=None):
    course = services.owned_course(request.user, course_pk)
    point = get_object_or_404(KnowledgePoint, pk=pk, course=course) if pk else None
    if course.is_archived:
        return forbidden(request)
    form = PointForm(request.POST or None, course=course, instance=point)
    if request.method == 'POST' and form.is_valid():
        try:
            services.save_point(request.user, course.pk, form.cleaned_data, pk)
        except (ValidationError, IntegrityError) as exc:
            form_error(form, exc)
        else:
            messages.success(request, '知识点已保存。')
            return redirect('course-detail', pk=course.pk)
    return render(request, 'learning/form.html', {'form': form, 'title': '编辑知识点' if pk else '添加知识点',
        'subtitle': course.name, 'section': 'courses', 'cancel_url': f'/courses/{course.pk}/'})


@login_required
def point_delete(request, course_pk, pk):
    course = services.owned_course(request.user, course_pk)
    point = get_object_or_404(KnowledgePoint, pk=pk, course=course)
    if course.is_archived:
        return forbidden(request)
    error = None
    if request.method == 'POST':
        try:
            services.delete_point(request.user, course.pk, pk)
        except ValidationError as exc:
            error = ' '.join(exc.messages)
        else:
            messages.success(request, '知识点已删除。')
            return redirect('course-detail', pk=course.pk)
    return render(request, 'learning/confirm.html', {'title': '删除知识点', 'object_title': point.name,
        'explanation': '只有未被任何错题引用的知识点才能删除。', 'error': error,
        'cancel_url': f'/courses/{course.pk}/', 'section': 'courses'})


@login_required
def point_choices(request, course_pk):
    course = services.owned_course(request.user, course_pk)
    values = list(course.knowledge_points.values('id', 'name')) if not course.is_archived else []
    return JsonResponse({'points': values})


@login_required
def task_list(request):
    tasks, archived = archive_filter(request, Task.objects.filter(course__owner=request.user).select_related('course'))
    course = selected_course(request)
    if course:
        tasks = tasks.filter(course=course)
    status = request.GET.get('status', 'all')
    if status == 'overdue':
        tasks = tasks.filter(status='todo', due_date__lt=timezone.localdate())
    elif status in ('todo', 'done'):
        tasks = tasks.filter(status=status)
    else:
        status = 'all'
    return render(request, 'learning/task_list.html', {'page_obj': page(request, tasks),
        'courses': Course.objects.filter(owner=request.user), 'selected_course': course,
        'status': status, 'archive': archived, 'section': 'tasks', 'title': '学习任务'})


@login_required
def task_edit(request, pk=None):
    task = get_object_or_404(Task.objects.select_related('course'), pk=pk, course__owner=request.user) if pk else None
    if task and task.course.is_archived:
        return forbidden(request)
    initial = {'course': selected_course(request).pk} if request.GET.get('course') else {}
    initial['token'] = services.make_token(request.user, 'task-create') if not pk else ''
    form = TaskForm(request.POST or None, user=request.user, instance=task, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            services.save_task(request.user, form.cleaned_data, pk, form.cleaned_data.get('token'))
        except (ValidationError, IntegrityError) as exc:
            form_error(form, exc)
        else:
            messages.success(request, '学习任务已保存。')
            return redirect('task-list')
    return render(request, 'learning/form.html', {'form': form, 'title': '编辑任务' if pk else '添加学习任务',
        'section': 'tasks', 'cancel_url': '/tasks/', 'needs_course': True})


@login_required
@require_POST
def task_status(request, pk):
    if request.POST.get('action') not in ('done', 'todo'):
        raise Http404()
    try:
        services.set_task_status(request.user, pk, request.POST['action'] == 'done')
    except ValidationError:
        return forbidden(request)
    messages.success(request, '任务状态已更新。')
    return redirect('task-list')


@login_required
def task_delete(request, pk):
    task = get_object_or_404(Task.objects.select_related('course'), pk=pk, course__owner=request.user)
    if task.course.is_archived:
        return forbidden(request)
    if request.method == 'POST':
        try:
            services.delete_task(request.user, pk)
        except ValidationError:
            return forbidden(request)
        messages.success(request, '任务已删除。')
        return redirect('task-list')
    return render(request, 'learning/confirm.html', {'title': '删除学习任务', 'object_title': task.title,
        'explanation': '确认后永久删除这条任务，请检查是否仍需保留。', 'cancel_url': '/tasks/', 'section': 'tasks'})


@login_required
def question_list(request):
    questions, archived = archive_filter(request, WrongQuestion.objects.filter(course__owner=request.user)
        .select_related('course').prefetch_related('knowledge_points'), question=True)
    course = selected_course(request)
    if course:
        questions = questions.filter(course=course)
    search = request.GET.get('q', '').strip()[:180]
    if search:
        questions = questions.filter(title__icontains=search)
    point = None
    if request.GET.get('point'):
        try:
            point_id = int(request.GET['point'])
        except (ValueError, TypeError):
            raise Http404()
        point = get_object_or_404(KnowledgePoint, pk=point_id, course__owner=request.user)
        questions = questions.filter(knowledge_points=point)
    points = KnowledgePoint.objects.filter(course__owner=request.user)
    if course:
        points = points.filter(course=course)
    return render(request, 'learning/question_list.html', {'page_obj': page(request, questions),
        'courses': Course.objects.filter(owner=request.user), 'points': points.select_related('course'),
        'selected_course': course, 'selected_point': point, 'q': search, 'archive': archived,
        'section': 'questions', 'title': '错题本'})


def owned_question(user, pk):
    return get_object_or_404(WrongQuestion.objects.select_related('course').prefetch_related('knowledge_points'),
        pk=pk, course__owner=user)


@login_required
def question_detail(request, pk):
    question = owned_question(request.user, pk)
    history = page(request, question.reviews.all().select_related('schedule_event').prefetch_related('image_snapshots__attachment'))
    for record in history:
        record.gallery_images = [image_data(link.attachment, link.role) for link in record.image_snapshots.all()]
    return render(request, 'learning/question_detail.html', {'question': question,
        'question_images': question_images(question),
        'page_obj': history, 'section': 'questions', 'title': question.title})


@login_required
def question_edit(request, pk=None):
    question = owned_question(request.user, pk) if pk else None
    if question and question.is_readonly:
        return forbidden(request)
    initial = {'course': selected_course(request).pk} if request.GET.get('course') else {}
    initial['token'] = services.make_token(request.user, 'question-create') if not pk else ''
    form = QuestionForm(request.POST or None, user=request.user, instance=question, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            question = services.save_question(request.user, form.cleaned_data, pk, form.cleaned_data.get('token'))
        except (ValidationError, IntegrityError) as exc:
            form_error(form, exc)
        else:
            messages.success(request, f'错题已保存，下次复习：{question.next_review_date:%Y-%m-%d}。')
            return redirect('question-detail', pk=question.pk)
    return render(request, 'learning/form.html', {'form': form, 'title': '编辑错题' if pk else '记录错题',
        'section': 'questions', 'cancel_url': f'/questions/{pk}/' if pk else '/questions/',
        'needs_course': True, 'question_form': True, 'initial_question_images': form_images(request.user, form, question)})


@login_required
@require_POST
def question_archive(request, pk):
    action = request.POST.get('action')
    if action not in ('archive', 'restore'):
        raise Http404()
    try:
        services.archive_question(request.user, pk, action == 'archive')
    except ValidationError:
        return forbidden(request)
    messages.success(request, '错题已归档，复习历史完整保留。' if action == 'archive' else '错题已恢复，原复习日期保持不变。')
    return redirect('question-detail', pk=pk)


def due_questions(user):
    return WrongQuestion.objects.filter(course__owner=user, course__is_archived=False,
        is_archived=False, next_review_date__lte=timezone.localdate()).select_related('course')


@login_required
def review_queue(request):
    return render(request, 'learning/review_queue.html', {'page_obj': page(request, due_questions(request.user)),
        'section': 'reviews', 'title': '今日复习'})


@login_required
def review_question(request, pk):
    question = owned_question(request.user, pk)
    revealed = False
    if request.method == 'POST' and request.POST.get('action') == 'save':
        form = ReviewForm(request.POST)
        try:
            services.read_token(request.POST.get('token'), request.user, 'review', pk, revealed=True)
            revealed = True
        except ValidationError as exc:
            form.is_valid()
            form_error(form, exc)
        else:
            if form.is_valid():
                try:
                    _, created = services.submit_review(request.user, pk, form.cleaned_data, form.cleaned_data['token'])
                except (ValidationError, IntegrityError) as exc:
                    form_error(form, exc)
                else:
                    messages.success(request, '复习已保存，下次日期已更新。' if created else '本次复习已保存，无需重复提交。')
                    next_question = due_questions(request.user).first()
                    return redirect('review-question', pk=next_question.pk) if next_question else redirect('review-queue')
    else:
        if question.is_readonly:
            return forbidden(request)
        if not question.is_due:
            messages.info(request, '这道题尚未到复习日期。')
            return redirect('review-queue')
        form = AnswerForm(request.POST or None, initial={'token': services.make_token(request.user, 'review', question)})
        if request.method == 'POST':
            if request.POST.get('action') != 'reveal':
                raise Http404()
            if form.is_valid():
                try:
                    token = services.reveal_token(form.cleaned_data['token'], request.user, question)
                except ValidationError as exc:
                    form_error(form, exc)
                else:
                    revealed = True
                    form = ReviewForm(initial={'answer': form.cleaned_data['answer'], 'token': token})
    suggestions = {}
    scheduling_error = None
    if revealed:
        try:
            suggestions = {key: suggest_schedule(request.user, question, key) for key in services.RATING_DAYS}
        except ValidationError as error:
            scheduling_error = ' '.join(error.messages)
    visible_images = [image for image in question_images(question) if revealed or image['role'] == 'question']
    return render(request, 'learning/review_question.html', {'question': question, 'form': form,
        'question_images': visible_images, 'schedule_suggestions': suggestions, 'scheduling_error': scheduling_error,
        'revealed': revealed, 'remaining': due_questions(request.user).count(), 'section': 'reviews', 'title': '专注复习',
        'suggested_dates': {key: proposal.due_date.isoformat() for key, proposal in suggestions.items()}})


@login_required
def statistics(request):
    today = timezone.localdate()
    data = request.GET if request.GET else {'start': today - timedelta(days=6), 'end': today}
    form = StatisticsForm(data, user=request.user)
    stats = None
    if form.is_valid():
        selected = form.cleaned_data['course']
        stats = services.summary(request.user, selected.pk if selected else None,
            form.cleaned_data['start'], form.cleaned_data['end'])
    return render(request, 'learning/statistics.html', {'form': form, 'stats': stats,
        'section': 'statistics', 'title': '学习统计'})


def not_found(request, exception=None):
    return render(request, 'learning/error.html', {'title': '未找到内容', 'code': '404',
        'description': '该内容不存在，或不属于当前账户。'}, status=404)


def forbidden(request, exception=None):
    return render(request, 'learning/error.html', {'title': '当前内容只读', 'code': '403',
        'description': '归档课程或错题不能修改。请先在详情页恢复，再继续操作。'}, status=403)


def server_error(request):
    return render(request, 'learning/error.html', {'title': '暂时无法完成操作', 'code': '500',
        'description': '请稍后重试。复习历史与复习安排会作为一个事务保存。'}, status=500)

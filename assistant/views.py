"""Session-authenticated, CSRF-protected JSON API. No HTML or model execution."""
import json
from functools import wraps
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.http import JsonResponse, Http404
from learning.models import Course, KnowledgePoint
from .models import ChatSession, Message, Draft
from . import services
from .providers import provider_status
from .serializers import session_data, message_data, draft_data


def api(methods):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({'error': 'authentication_required', 'detail': '请先登录。'}, status=401)
            if request.method not in methods:
                response = JsonResponse({'error': 'method_not_allowed'}, status=405)
                response['Allow'] = ', '.join(methods)
                return response
            try:
                response = view(request, *args, **kwargs)
            except Http404:
                return JsonResponse({'error': 'not_found', 'detail': '未找到属于当前用户的内容。'}, status=404)
            except services.Conflict as exc:
                return JsonResponse({'error': 'conflict', 'detail': exc.messages}, status=409)
            except ValidationError as exc:
                return JsonResponse({'error': 'validation_error', 'detail': getattr(exc, 'message_dict', exc.messages)}, status=400)
            except IntegrityError:
                return JsonResponse({'error': 'conflict', 'detail': '提交已冲突，请重新读取内容后再试。'}, status=409)
            response['Cache-Control'] = 'no-store'
            response['X-Content-Type-Options'] = 'nosniff'
            return response
        return wrapped
    return decorate


def _body(request, allowed, required=()):
    if request.content_type != 'application/json':
        raise ValidationError('请使用 application/json 提交。')
    if len(request.body) > 750000:
        raise ValidationError('单次文字提交过大。')
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise ValidationError('JSON 内容无效。')
    if not isinstance(data, dict) or set(data) - set(allowed) or set(required) - set(data):
        raise ValidationError('缺少必需字段或包含不支持的字段。')
    return data


@api(['GET'])
def status(request):
    return JsonResponse(provider_status(request.user))


@api(['GET'])
def context(request):
    courses = list(Course.objects.filter(owner=request.user, is_archived=False).order_by('name', 'pk').values('id', 'name'))
    points = KnowledgePoint.objects.filter(course__owner=request.user, course__is_archived=False).order_by('name', 'pk')
    by_course = {}
    for point in points.values('id', 'name', 'course_id'):
        by_course.setdefault(point['course_id'], []).append({'id': point['id'], 'name': point['name']})
    for course in courses:
        course['knowledge_points'] = by_course.get(course['id'], [])
    return JsonResponse({'courses': courses, 'provider': provider_status(request.user), 'scope': 'current_user_active_courses_for_local_form_only'})


@api(['GET', 'POST'])
def sessions(request):
    if request.method == 'GET':
        query = ChatSession.objects.filter(owner=request.user)
        before = request.GET.get('before')
        if before:
            cursor = services.owned_session(request.user, services.uuid_value(before, 'before'))
            query = query.filter(Q(updated_at__lt=cursor.updated_at) | Q(updated_at=cursor.updated_at, pk__lt=cursor.pk))
        rows = list(query[:101])
        return JsonResponse({'sessions': [session_data(row) for row in rows[:100]], 'has_more': len(rows) > 100,
            'older_cursor': str(rows[99].pk) if len(rows) > 100 else None, 'local_only': True})
    data = _body(request, {'title', 'submission_key'}, {'submission_key'})
    row, created = services.create_session(request.user, data.get('title', '新会话'), data['submission_key'])
    return JsonResponse({'session': session_data(row), 'created': created}, status=201 if created else 200)


@api(['GET', 'PATCH'])
def session_detail(request, session_id):
    session = services.owned_session(request.user, session_id)
    if request.method == 'PATCH':
        data = _body(request, {'title'}, {'title'})
        session = services.rename_session(request.user, session_id, data['title'])
        return JsonResponse({'session': session_data(session)})
    query = session.messages.all()
    before = request.GET.get('before')
    if before:
        try:
            cursor = query.get(pk=services.uuid_value(before, 'before'))
        except Message.DoesNotExist:
            raise Http404()
        query = query.filter(Q(created_at__lt=cursor.created_at) | Q(created_at=cursor.created_at, pk__lt=cursor.pk))
    newest = list(query.order_by('-created_at', '-pk').select_related('chosen_context').prefetch_related('image_links__attachment')[:101])
    messages = newest[:100]
    messages.reverse()
    return JsonResponse({'session': session_data(session), 'messages': [{**message_data(item), 'selection': services.message_selection(request.user, item)} for item in messages],
        'has_older': len(newest) > 100, 'older_cursor': str(messages[0].pk) if len(newest) > 100 else None,
        'drafts': [draft_data(draft) for draft in session.drafts.filter(owner=request.user)[:100]], 'local_only': True})


@api(['POST'])
def messages(request, session_id):
    data = _body(request, {'text', 'attachment_ids', 'submission_key', 'context_message_ids', 'selected_target', 'selected_course_id'}, {'submission_key'})
    message, response, created = services.append_message(request.user, session_id,
        data.get('text', ''), data.get('attachment_ids', []), data['submission_key'],
        context_message_ids=data.get('context_message_ids', []), selected_target=data.get('selected_target'),
        selected_course_id=data.get('selected_course_id'))
    return JsonResponse({'message': message_data(message),
        'response': message_data(response) if response else None, 'created': created,
        'provider': provider_status(request.user), 'selection': services.message_selection(request.user, message),
        'drafts': [draft_data(draft) for draft in message.drafts.filter(owner=request.user)]}, status=201 if created else 200)


@api(['GET'])
def target(request, kind, target_id):
    return JsonResponse(services.target_preview(request.user, kind, target_id))


@api(['GET'])
def target_choices(request):
    before = request.GET.get('before')
    if before is not None:
        try:
            before = int(before)
        except (TypeError, ValueError):
            raise ValidationError('候选分页标识无效。')
    return JsonResponse(services.target_candidates(request.user, request.GET.get('kind', 'task'),
                                                  request.GET.get('query', ''), before))


@api(['GET', 'POST'])
def drafts(request, session_id):
    session = services.owned_session(request.user, session_id)
    if request.method == 'GET':
        query = session.drafts.filter(owner=request.user)
        before = request.GET.get('before')
        if before:
            cursor = services.owned_draft(request.user, services.uuid_value(before, 'before'))
            if cursor.session_id != session.pk:
                raise Http404()
            query = query.filter(Q(created_at__lt=cursor.created_at) | Q(created_at=cursor.created_at, pk__lt=cursor.pk))
        rows = list(query[:101])
        return JsonResponse({'drafts': [draft_data(item) for item in rows[:100]],
            'has_more': len(rows) > 100, 'older_cursor': str(rows[99].pk) if len(rows) > 100 else None})
    data = _body(request, {'operation', 'payload', 'target_id', 'expected_version', 'submission_key', 'title'}, {'operation', 'payload', 'submission_key'})
    draft, created = services.create_draft(request.user, session.pk, data)
    return JsonResponse({'draft': draft_data(draft), 'created': created}, status=201 if created else 200)


@api(['GET'])
def draft_detail(request, draft_id):
    return JsonResponse({'draft': draft_data(services.owned_draft(request.user, draft_id))})


@api(['POST'])
def confirm(request, draft_id):
    data = _body(request, {'confirmation_token', 'submission_key'}, {'confirmation_token', 'submission_key'})
    token = services._text(data['confirmation_token'], 'confirmation_token', 3000, required=True)
    draft, applied = services.confirm_draft(request.user, draft_id, token, data['submission_key'])
    return JsonResponse({'draft': draft_data(draft), 'applied': applied, 'replayed': not applied})


@api(['POST'])
def cancel(request, draft_id):
    _body(request, set(), set())
    draft = services.cancel_draft(request.user, draft_id)
    return JsonResponse({'draft': draft_data(draft), 'cancelled': True})

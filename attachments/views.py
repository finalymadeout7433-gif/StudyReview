from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.http import FileResponse, Http404, JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from .services import owned_attachment, open_attachment_file, upload_attachment


@transaction.non_atomic_requests
@login_required
@require_POST
@csrf_protect
def upload(request):
    files = request.FILES
    if getattr(request, 'attachment_upload_error', None):
        return JsonResponse({'error': request.attachment_upload_error}, status=413)
    if set(files) != {'file'} or len(files.getlist('file')) != 1:
        return JsonResponse({'error': '请一次选择一张图片。'}, status=400)
    try:
        attachment = upload_attachment(request.user, files['file'])
    except ValidationError as error:
        return JsonResponse({'error': ' '.join(error.messages)}, status=400)
    except (OSError, DatabaseError):
        return JsonResponse({'error': '本地图片存储或数据库暂不可用，请稍后重试。'}, status=503)
    response = JsonResponse({'id': str(attachment.pk),
        'url': reverse('attachments:media', kwargs={'attachment_id': attachment.pk}),
        'thumbnail_url': reverse('attachments:thumbnail', kwargs={'attachment_id': attachment.pk}),
        'name': attachment.display_name, 'width': attachment.width, 'height': attachment.height}, status=201)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _media_response(request, attachment_id, thumbnail=False):
    attachment = owned_attachment(request.user, attachment_id)
    try:
        source = open_attachment_file(attachment, thumbnail=thumbnail)
    except ValidationError:
        raise Http404('图片暂不可读。')
    response = FileResponse(source, content_type='image/png', filename='学习图片.png', as_attachment=False)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cross-Origin-Resource-Policy'] = 'same-origin'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


@login_required
@require_GET
def media(request, attachment_id):
    return _media_response(request, attachment_id)


@login_required
@require_GET
def thumbnail(request, attachment_id):
    return _media_response(request, attachment_id, thumbnail=True)

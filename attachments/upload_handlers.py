"""Django streaming upload limits, installed before CSRF parses multipart bodies."""
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.http import JsonResponse

from .services import MAX_INPUT_BYTES

MAX_REQUEST_BYTES = MAX_INPUT_BYTES + 1024 * 1024


class ImageUploadLimitHandler(FileUploadHandler):
    chunk_size = 64 * 1024

    def __init__(self, request=None):
        super().__init__(request)
        self.received = 0
        self.file_count = 0

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.file_count += 1
        self.received = 0
        if self.file_count > 1:
            self.request.attachment_upload_error = '请一次上传一张图片。'
            raise StopUpload(connection_reset=False)
        if self.content_length and self.content_length > MAX_INPUT_BYTES:
            self.request.attachment_upload_error = '每张图片不能超过 8 MB。'
            raise StopUpload(connection_reset=False)

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > MAX_INPUT_BYTES:
            self.request.attachment_upload_error = '每张图片不能超过 8 MB。'
            raise StopUpload(connection_reset=False)
        return raw_data

    def file_complete(self, file_size):
        return None


class ImageUploadLimitMiddleware:
    """Place before django.middleware.csrf.CsrfViewMiddleware.

    Only the dedicated image upload endpoint is intercepted. Upload services still enforce
    their own byte and format limits when called without an HTTP request.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.rstrip('/') == '/attachments/upload' and request.method == 'POST':
            try:
                length = int(request.META.get('CONTENT_LENGTH', '0'))
            except (ValueError, TypeError):
                return JsonResponse({'error': '上传请求长度无效。'}, status=400)
            if length < 0:
                return JsonResponse({'error': '上传请求长度无效。'}, status=400)
            if length > MAX_REQUEST_BYTES:
                return JsonResponse({'error': '每张图片不能超过 8 MB。'}, status=413)
            request.upload_handlers.insert(0, ImageUploadLimitHandler(request))
        return self.get_response(request)

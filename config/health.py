from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from .version import BUILD_VERSION


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            ready = cursor.fetchone()[0] == 1
    except Exception:
        ready = False
    # `version` is the desktop control protocol, kept compatible with an already
    # running preview. `build_version` identifies the application users opened.
    response = JsonResponse({'app': 'studyreview', 'version': '2.0',
                             'build_version': BUILD_VERSION, 'db': ready}, status=200 if ready else 503)
    response['Cache-Control'] = 'no-store'
    return response

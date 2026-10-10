from django.urls import include, path
from .health import health

urlpatterns = [
    path('health/', health, name='health'),
    path('attachments/', include('attachments.urls')),
    path('assistant/', include('assistant.urls')),
    path('ai/', include('ai_gateway.urls')),
    path('', include('learning.urls')),
]
handler404 = 'learning.views.not_found'
handler403 = 'learning.views.forbidden'
handler500 = 'learning.views.server_error'

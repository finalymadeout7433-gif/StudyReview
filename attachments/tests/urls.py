from django.http import HttpResponse
from django.urls import include, path

urlpatterns = [
    path('attachments/', include('attachments.urls')),
    path('accounts/login/', lambda request: HttpResponse('本地登录'), name='login'),
]

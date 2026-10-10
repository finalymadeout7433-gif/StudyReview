from django.urls import path
from . import views

app_name = 'attachments'
urlpatterns = [
    path('upload/', views.upload, name='upload'),
    path('<uuid:attachment_id>/', views.media, name='media'),
    path('<uuid:attachment_id>/thumbnail/', views.thumbnail, name='thumbnail'),
]

from django.urls import path
from . import views

app_name = 'ai_gateway'
urlpatterns = [path('config/', views.config, name='config')]

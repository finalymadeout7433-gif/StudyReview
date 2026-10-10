from django.urls import path
from . import views

app_name = 'assistant'
urlpatterns = [
    path('status/', views.status, name='status'),
    path('context/', views.context, name='context'),
    path('sessions/', views.sessions, name='sessions'),
    path('sessions/<uuid:session_id>/', views.session_detail, name='session'),
    path('sessions/<uuid:session_id>/messages/', views.messages, name='messages'),
    path('sessions/<uuid:session_id>/drafts/', views.drafts, name='drafts'),
    path('targets/<str:kind>/<int:target_id>/', views.target, name='target'),
    path('targets/', views.target_choices, name='target-choices'),
    path('drafts/<uuid:draft_id>/', views.draft_detail, name='draft'),
    path('drafts/<uuid:draft_id>/confirm/', views.confirm, name='confirm'),
    path('drafts/<uuid:draft_id>/cancel/', views.cancel, name='cancel'),
]

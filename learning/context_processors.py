from django.utils import timezone
from django.conf import settings

def navigation(request):
    return {'today': timezone.localdate(),
            'mi_avatar_available': ((settings.BASE_DIR / 'static' / 'img' / 'mi-avatar.png').is_file()
                                    or (settings.STATIC_ROOT / 'img' / 'mi-avatar.png').is_file()),
            'navigation': [
        ('dashboard', '学习概览', 'overview'), ('course-list', '课程与知识点', 'courses'),
        ('task-list', '学习任务', 'tasks'), ('question-list', '错题本', 'questions'),
        ('review-queue', '今日复习', 'reviews'), ('statistics', '学习统计', 'statistics'),
    ]}

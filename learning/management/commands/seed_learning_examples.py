"""Explicit examples for one existing user; no resets, deletes or credentials."""
import uuid
from datetime import datetime, time, timedelta, timezone as utc
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from learning import services
from learning.example_curriculum import CURRICULUM
from learning.models import Course, KnowledgePoint, Task, WrongQuestion

NAMESPACE = uuid.UUID('808e79f8-8273-4fbb-9ad1-eb9e0b547c45')


def example_key(user, kind, course_index, index):
    return uuid.uuid5(NAMESPACE, f'curriculum-v1:{user.pk}:{kind}:{course_index}:{index}')


class Command(BaseCommand):
    help = '为指定已存在的开发账户添加标记清楚的课程示例；不改密码、不删除、不覆盖。'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)
        parser.add_argument('--with-example-history', action='store_true')
        parser.add_argument('--dry-run', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        database = connection.settings_dict['NAME']
        if connection.vendor == 'mysql' and database not in {
                getattr(settings, 'V2_DEVELOPMENT_DATABASE', None),
                connection.settings_dict.get('TEST', {}).get('NAME')}:
            raise CommandError('只允许在已配置的独立开发或测试数据库中导入示例。')
        try:
            user = User.objects.select_for_update().get(username=options['username'], is_active=True)
        except User.DoesNotExist:
            raise CommandError('找不到该有效账户；请先自行注册。')
        today = timezone.localdate()
        counts = {'courses_created': 0, 'points_created': 0, 'tasks_created': 0, 'questions_created': 0, 'example_reviews_created': 0}
        for ci, item in enumerate(CURRICULUM):
            course, created = Course.objects.get_or_create(owner=user, name=item['name'],
                defaults={'description': item['description']})
            counts['courses_created'] += int(created)
            if course.is_archived:
                raise CommandError('清单中存在已归档课程；保留原状态，本次导入回滚。')
            if not course.description.strip():
                course.description = item['description']
                course.save(update_fields=['description'])
            points = []
            for name in item['points']:
                point, created = KnowledgePoint.objects.get_or_create(course=course, name=name)
                points.append(point)
                counts['points_created'] += int(created)
            for ti, (title, description) in enumerate(item['tasks']):
                key = example_key(user, 'task', ci, ti)
                existing = Task.objects.filter(creation_key=key).first()
                if existing:
                    if existing.course_id != course.pk:
                        raise CommandError('示例标识冲突，未覆盖已有任务。')
                    continue
                offset = [-4-ci, [-2, 0, 1, 2, -1, 3, 4][ci], 3+ci, 7+ci][ti]
                done = ti == 0
                task = Task(course=course, creation_key=key, title=title,
                    description=description,
                    due_date=today+timedelta(days=offset), status='done' if done else 'todo',
                    completed_at=timezone.now()-timedelta(days=2) if done else None)
                task.full_clean()
                task.save()
                counts['tasks_created'] += 1
            for qi, row in enumerate(item['questions']):
                key = example_key(user, 'question', ci, qi)
                existing = WrongQuestion.objects.filter(creation_key=key).first()
                if existing:
                    if existing.course_id != course.pk:
                        raise CommandError('示例标识冲突，未覆盖已有错题。')
                    # Never replay examples over an edited question or real history.
                    continue
                title, content, original, correct, reason, point_indexes = row
                first_day = today-timedelta(days=25-ci-qi*7)
                stamp = datetime.combine(first_day, time(10,30), tzinfo=ZoneInfo('Asia/Shanghai')).astimezone(utc.utc)
                question = WrongQuestion(course=course, creation_key=key, title=title,
                    content=content, original_answer=original, correct_answer=correct,
                    error_reason=reason, next_review_date=first_day if options['with_example_history'] else today)
                with patch('django.utils.timezone.now', return_value=stamp-timedelta(days=1)):
                    question.full_clean()
                    question.save()
                    for pi in point_indexes:
                        question.knowledge_points.through.objects.create(question=question, knowledge_point=points[pi])
                counts['questions_created'] += 1
                if not options['with_example_history']:
                    continue
                pattern = [('again', 'hard', 'good'), ('hard', 'good', 'good'),
                    ('again', 'hard', ['again','good','hard'][ci%3])][qi]
                for ri, offset in enumerate((0, 1, 4)):
                    moment = stamp+timedelta(days=offset)
                    if moment >= timezone.now():
                        raise CommandError('示例时间落在未来，本次回滚。')
                    next_day = first_day+timedelta(days=(1,4)[ri]) if ri<2 else max(
                        moment.astimezone(ZoneInfo('Asia/Shanghai')).date()+timedelta(days=1),
                        today+timedelta(days=[-2,-1,0,1,2,4,7][(ci+qi)%7]))
                    with patch('django.utils.timezone.now', return_value=moment):
                        question.refresh_from_db()
                        token = services.reveal_token(services.make_token(user,'review',question),user,question)
                        services.submit_review(user, question.pk, {
                            'answer': '示例演练：'+(original if pattern[ri]=='again' else correct),
                            'rating': pattern[ri], 'next_review_date': next_day,
                            'note': '示例演练历史，由课程内容初始化生成；不是本人实际作答。'}, token, is_example=True)
                    counts['example_reviews_created'] += 1
        if options['dry_run']:
            transaction.set_rollback(True)
        self.stdout.write(('DRY RUN, rolled back: ' if options['dry_run'] else 'Examples added: ')+str(counts))

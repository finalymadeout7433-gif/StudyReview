import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models import Q, F
from django.utils import timezone


class Course(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='courses')
    name = models.CharField('课程名称', max_length=120)
    description = models.TextField('课程说明', blank=True)
    is_archived = models.BooleanField('已归档', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name', 'pk']
        constraints = [models.UniqueConstraint(fields=['owner', 'name'], name='course_owner_name_uq')]
        indexes = [models.Index(fields=['owner', 'is_archived'], name='course_owner_archive_idx')]

    def __str__(self):
        return self.name


class KnowledgePoint(models.Model):
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='knowledge_points')
    name = models.CharField('知识点名称', max_length=120)

    class Meta:
        ordering = ['name', 'pk']
        constraints = [models.UniqueConstraint(fields=['course', 'name'], name='point_course_name_uq')]

    def __str__(self):
        return self.name


class Task(models.Model):
    class Status(models.TextChoices):
        TODO = 'todo', '未完成'
        DONE = 'done', '已完成'

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='tasks')
    title = models.CharField('任务标题', max_length=180)
    description = models.TextField('任务说明', blank=True)
    due_date = models.DateField('截止日期')
    status = models.CharField('状态', max_length=4, choices=Status.choices, default=Status.TODO)
    completed_at = models.DateTimeField('完成时间', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    creation_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ['due_date', 'pk']
        indexes = [models.Index(fields=['course', 'status', 'due_date'], name='task_course_status_due_idx')]
        constraints = [models.CheckConstraint(condition=(
            Q(status='todo', completed_at__isnull=True) | Q(status='done', completed_at__isnull=False)
        ), name='task_completion_consistent')]

    @property
    def is_overdue(self):
        return self.status == self.Status.TODO and self.due_date < timezone.localdate()


class WrongQuestion(models.Model):
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='questions')
    title = models.CharField('错题标题', max_length=180)
    content = models.TextField('题目正文', max_length=20000, validators=[MaxLengthValidator(20000)])
    original_answer = models.TextField('原答案', max_length=20000, validators=[MaxLengthValidator(20000)])
    correct_answer = models.TextField('参考答案', max_length=20000, validators=[MaxLengthValidator(20000)])
    error_reason = models.TextField('错误原因', max_length=20000, validators=[MaxLengthValidator(20000)])
    next_review_date = models.DateField('下次复习日期')
    is_archived = models.BooleanField('已归档', default=False)
    knowledge_points = models.ManyToManyField(KnowledgePoint, through='QuestionKnowledgePoint', related_name='questions', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    creation_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ['next_review_date', 'pk']
        indexes = [models.Index(fields=['course', 'is_archived', 'next_review_date'], name='question_course_due_idx')]

    @property
    def is_due(self):
        return not self.is_archived and not self.course.is_archived and self.next_review_date <= timezone.localdate()

    @property
    def is_readonly(self):
        return self.is_archived or self.course.is_archived


class QuestionKnowledgePoint(models.Model):
    question = models.ForeignKey(WrongQuestion, on_delete=models.CASCADE, related_name='point_links')
    knowledge_point = models.ForeignKey(KnowledgePoint, on_delete=models.PROTECT, related_name='question_links')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['question', 'knowledge_point'], name='question_point_uq')]

    def clean(self):
        if self.question_id and self.knowledge_point_id and self.question.course_id != self.knowledge_point.course_id:
            raise ValidationError('知识点必须属于错题所在课程。')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ImmutableReviewQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('复习历史不可修改。')

    def delete(self):
        raise ValidationError('复习历史不可删除。')

    def bulk_update(self, *args, **kwargs):
        raise ValidationError('复习历史不可修改。')


class ReviewRecord(models.Model):
    class Rating(models.TextChoices):
        AGAIN = 'again', '不会'
        HARD = 'hard', '不熟'
        GOOD = 'good', '掌握'

    question = models.ForeignKey(WrongQuestion, on_delete=models.PROTECT, related_name='reviews')
    reviewed_at = models.DateTimeField(default=timezone.now)
    review_date = models.DateField('本次复习日期')
    answer = models.TextField('本次作答', max_length=20000, validators=[MaxLengthValidator(20000)])
    rating = models.CharField('自评', max_length=5, choices=Rating.choices)
    note = models.TextField('备注', blank=True, max_length=5000, validators=[MaxLengthValidator(5000)])
    next_review_date = models.DateField('当次安排的下次日期')
    title_snapshot = models.CharField(max_length=180)
    question_snapshot = models.TextField()
    original_answer_snapshot = models.TextField()
    correct_answer_snapshot = models.TextField()
    error_reason_snapshot = models.TextField()
    course_snapshot = models.CharField(max_length=120)
    knowledge_points_snapshot = models.JSONField(default=list, blank=True)
    submission_key = models.UUIDField(unique=True)
    objects = ImmutableReviewQuerySet.as_manager()

    class Meta:
        ordering = ['-reviewed_at', '-pk']
        indexes = [models.Index(fields=['question', 'review_date'], name='review_question_date_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(rating__in=['again', 'hard', 'good']), name='review_rating_valid'),
            models.CheckConstraint(condition=Q(next_review_date__gt=F('review_date')), name='review_next_after_today'),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('复习历史不可修改。')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('复习历史不可删除。')

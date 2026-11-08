import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models import Q, F
from django.utils import timezone


class FocusSession(models.Model):
    task = models.ForeignKey('Task', null=True, blank=True, on_delete=models.SET_NULL, related_name='focus_sessions')
    task_title = models.CharField(max_length=180, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='focus_sessions')
    course = models.ForeignKey('Course', null=True, blank=True, on_delete=models.PROTECT, related_name='focus_sessions')
    target_seconds = models.PositiveIntegerField(default=1500)
    status = models.CharField(max_length=10, default='running', choices=[('running','专注中'),('paused','已暂停'),('finished','已结束')])
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    active_owner_key = models.GeneratedField(
        expression=models.Case(models.When(status__in=['running','paused'],then=F('owner_id')),default=None),
        output_field=models.BigIntegerField(),db_persist=True,unique=True,null=True,
    )

    class Meta:
        ordering = ['-started_at', '-pk']
        indexes = [models.Index(fields=['owner','status'], name='focus_owner_status_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(target_seconds__gte=300, target_seconds__lte=5400), name='focus_target_bounds'),
            models.CheckConstraint(condition=Q(status__in=['running','paused'],ended_at__isnull=True)|Q(status='finished',ended_at__isnull=False),name='focus_end_consistent'),
        ]

    def clean(self):
        if self.task_id and self.task.course_id != self.course_id:
            raise ValidationError('专注任务必须属于所选课程。')
        if self.course_id and self.course.owner_id != self.owner_id:
            raise ValidationError('专注课程必须属于当前账户。')


class FocusInterval(models.Model):
    session = models.ForeignKey(FocusSession, on_delete=models.PROTECT, related_name='intervals')
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['started_at','pk']
        constraints = [models.CheckConstraint(condition=Q(ended_at__isnull=True)|Q(ended_at__gte=F('started_at')), name='focus_interval_order')]


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


class Chapter(models.Model):
    """A course has chapters and one optional level of sections beneath them."""
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='chapters')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='children', verbose_name='所属章')
    name = models.CharField('章节名称', max_length=120)
    position = models.PositiveIntegerField('排序', default=0)

    class Meta:
        ordering = ['position', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['course', 'name'], name='chapter_course_name_uq'),
        ]
        indexes = [models.Index(fields=['course', 'parent', 'position'], name='chapter_course_tree_idx')]

    def clean(self):
        super().clean()
        if self.parent_id:
            if self.parent_id == self.pk or self.parent.course_id != self.course_id:
                raise ValidationError({'parent': '上级必须是本课程的其他章节。'})
            if self.parent.parent_id:
                raise ValidationError({'parent': '支持“章 → 节”两层目录，请选择顶层章。'})
            if self.pk and self.children.exists():
                raise ValidationError({'parent': '此章下已有节，不能再移入其他章。'})

    def __str__(self):
        return self.name


class KnowledgePoint(models.Model):
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='knowledge_points')
    chapter = models.ForeignKey(Chapter, verbose_name='所属章节', null=True, blank=True, on_delete=models.PROTECT, related_name='knowledge_points')
    name = models.CharField('知识点名称', max_length=120)

    class Meta:
        ordering = ['name', 'pk']
        constraints = [models.UniqueConstraint(fields=['course', 'name'], name='point_course_name_uq')]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.chapter_id and self.chapter.course_id != self.course_id:
            raise ValidationError({'chapter': '章节必须属于知识点所在课程。'})


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
    is_example = models.BooleanField('示例演练记录', default=False)
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
        indexes = [models.Index(fields=['question', 'review_date'], name='review_question_date_idx'),
                   models.Index(fields=['question', 'reviewed_at', 'rating', 'is_example'],
                                name='review_question_time_idx')]
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

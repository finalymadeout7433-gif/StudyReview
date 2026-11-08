"""Owner-scoped due queues and per-round skips; skips never alter learning records."""
import time
import uuid
from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from .models import Chapter, Course, KnowledgePoint, WrongQuestion


class ReviewScope:
    def __init__(self, request):
        self.request = request
        params = request.GET

        def owned(model, key):
            value = params.get(key)
            if not value:
                return None
            if not value.isascii() or not value.isdecimal():
                raise Http404()
            owner = {'owner': request.user} if model is Course else {'course__owner': request.user}
            return get_object_or_404(model, pk=value, **owner)

        self.course = owned(Course, 'course')
        self.chapter = owned(Chapter, 'chapter')
        self.point = owned(KnowledgePoint, 'point')
        self.search = params.get('q', '').strip()[:180]
        for item in (self.chapter, self.point):
            if item:
                if self.course and item.course_id != self.course.pk:
                    raise Http404()
                self.course = self.course or item.course
        self.questions = WrongQuestion.objects.filter(course__owner=request.user)
        labels = []
        if self.course:
            self.questions = self.questions.filter(course=self.course)
            labels.append(self.course.name)
        if self.chapter:
            chapters = Chapter.objects.filter(Q(pk=self.chapter.pk) | Q(parent=self.chapter))
            if self.point and self.point.chapter_id not in chapters.values_list('pk', flat=True):
                raise Http404()
            self.questions = self.questions.filter(knowledge_points__chapter__in=chapters)
            labels.append(self.chapter.name + ('（含下级节）' if not self.chapter.parent_id else ''))
        if self.point:
            self.questions = self.questions.filter(knowledge_points=self.point)
            labels.append(self.point.name)
        if self.search:
            self.questions = self.questions.filter(title__icontains=self.search)
            labels.append('标题包含“' + self.search + '”')
        self.questions = self.questions.distinct()
        self.label = ' / '.join(labels) if labels else '全部课程'
        self.params = {key: str(item.pk) for key, item in
                       [('course', self.course), ('chapter', self.chapter), ('point', self.point)] if item}
        if self.search:
            self.params['q'] = self.search
        self.key = urlencode(self.params)
        self.flow = None
        self.skipped = []
        token = params.get('round')
        if token:
            state = request.session.get('review_rounds', {}).get(token)
            if state and time.time() - state['created'] < 86400:
                if state['owner'] != request.user.pk or state['scope'] != self.key:
                    raise Http404()
                self.flow, self.skipped = token, state['skipped']
            else:
                messages.info(request, '本轮暂时跳过记录已失效，已恢复当前范围全部到期题。')

    def due(self):
        return self.questions.filter(course__is_archived=False, is_archived=False,
                                     next_review_date__lte=timezone.localdate()).select_related('course')

    def pending(self):
        return self.due().exclude(pk__in=self.skipped)

    def url(self, name='review-queue', pk=None, reset=False):
        params = self.params.copy()
        if self.flow and not reset:
            params['round'] = self.flow
        query = urlencode(params)
        return reverse(name, args=[pk] if pk is not None else []) + ('?' + query if query else '')

    def next_url(self):
        question = self.pending().first()
        return self.url('review-question', question.pk) if question else self.url()

    def skip(self, question):
        rounds = self.request.session.get('review_rounds', {}).copy()
        now = time.time()
        rounds = {key: value for key, value in rounds.items() if now - value['created'] < 86400}
        if self.flow is None:
            self.flow = uuid.uuid4().hex
            # Bound browser-session metadata; older rounds expire without altering due dates.
            rounds = dict(sorted(rounds.items(), key=lambda item: item[1]['created'])[-19:])
            rounds[self.flow] = {'owner': self.request.user.pk, 'scope': self.key,
                                 'created': now, 'skipped': []}
        if question.pk not in self.skipped:
            if len(self.skipped) >= 2000:
                messages.info(self.request, '本轮暂时跳过已达2000题，请回到列表重新查看跳过题。')
                return self.url()
            self.skipped = [*self.skipped, question.pk]
        rounds[self.flow]['skipped'] = self.skipped
        self.request.session['review_rounds'] = rounds
        return self.next_url()

    @property
    def query_string(self):
        params = {**self.params, **({'round': self.flow} if self.flow else {})}
        return '?' + urlencode(params) if params else ''

    def context(self):
        pending = self.pending().count()
        skipped = self.due().filter(pk__in=self.skipped).count()
        return {'review_scope': self, 'scope_label': self.label,
                'scope_queue_url': self.url(), 'scope_reset_url': self.url(reset=True),
                'scope_questions_url': self.url('question-list', reset=True),
                'review_query': self.query_string,
                'remaining': pending, 'skipped_count': skipped, 'scope_total': pending + skipped}

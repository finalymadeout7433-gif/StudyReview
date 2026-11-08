from datetime import timedelta
from urllib.parse import urlsplit, parse_qs

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.utils import timezone

from learning.models import Course, Chapter, KnowledgePoint, WrongQuestion, QuestionKnowledgePoint, ReviewRecord
from learning import services


class ReviewScopeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('scope-owner')
        self.other = get_user_model().objects.create_user('scope-other')
        self.course = Course.objects.create(owner=self.user, name='数据库')
        self.second = Course.objects.create(owner=self.user, name='算法')
        self.root = Chapter.objects.create(course=self.course, name='关系模型')
        self.child = Chapter.objects.create(course=self.course, parent=self.root, name='关系代数')
        self.outside = Chapter.objects.create(course=self.course, name='SQL')
        self.point = KnowledgePoint.objects.create(course=self.course, chapter=self.child, name='投影')
        self.sql_point = KnowledgePoint.objects.create(course=self.course, chapter=self.outside, name='连接')
        self.today = timezone.localdate()
        self.first = self.question('关系练习一', [self.point, self.sql_point], -2)
        self.next = self.question('关系练习二', [self.point], 0)
        self.unrelated = self.question('SQL查询', [self.sql_point], -3)
        self.future = self.question('未来关系题', [self.point], 2)
        self.archived = self.question('归档关系题', [self.point], -4, archived=True)
        self.foreign_course = Course.objects.create(owner=self.other, name='他人资料')
        self.foreign_chapter = Chapter.objects.create(course=self.foreign_course, name='不可访问')
        self.query = f'?course={self.course.pk}&chapter={self.root.pk}'
        self.client.force_login(self.user)

    def question(self, title, points, offset, archived=False):
        q = WrongQuestion.objects.create(course=self.course, title=title, content='题目', original_answer='原答',
            correct_answer='参考', error_reason='概念混淆', next_review_date=self.today+timedelta(days=offset), is_archived=archived)
        for point in points:
            QuestionKnowledgePoint.objects.create(question=q, knowledge_point=point)
        return q

    def save(self, question, query=None, token=None):
        token = token or services.reveal_token(services.make_token(self.user, 'review', question), self.user, question)
        return self.client.post(f'/reviews/{question.pk}/' + (self.query if query is None else query),
            {'action': 'save', 'answer': '独立作答', 'rating': 'good', 'token': token})

    def test_parent_child_and_cross_chapter_question_count_once(self):
        for chapter in (self.root, self.child):
            response = self.client.get(f'/reviews/?chapter={chapter.pk}')
            self.assertEqual([q.pk for q in response.context['page_obj']], [self.first.pk, self.next.pk])
            self.assertEqual(response.context['remaining'], 2)
            self.assertContains(response, '本轮复习范围')
        sql = self.client.get(f'/reviews/?chapter={self.outside.pk}')
        self.assertEqual(set(q.pk for q in sql.context['page_obj']), {self.first.pk, self.unrelated.pk})

    def test_save_stays_in_chapter_and_last_question_returns_scoped_empty(self):
        response = self.save(self.first)
        self.assertEqual(response.url, f'/reviews/{self.next.pk}/'+self.query)
        token = services.reveal_token(services.make_token(self.user, 'review', self.next), self.user, self.next)
        response = self.save(self.next, token=token)
        self.assertEqual(response.url, '/reviews/'+self.query)
        empty = self.client.get(response.url)
        self.assertContains(empty, '当前范围没有到期错题')
        self.assertEqual(empty.context['scope_total'], 0)
        self.assertTrue(self.unrelated.is_due)
        self.assertEqual(ReviewRecord.objects.count(), 2)
        self.save(self.next, token=token)
        self.assertEqual(ReviewRecord.objects.count(), 2)

    def test_point_search_course_and_future_redirect_keep_scope(self):
        query = f'?point={self.point.pk}&q=练习二'
        response = self.client.get('/reviews/'+query)
        self.assertEqual([q.pk for q in response.context['page_obj']], [self.next.pk])
        response = self.save(self.next, query=query)
        params = parse_qs(urlsplit(response.url).query)
        self.assertEqual(params['point'], [str(self.point.pk)])
        self.assertEqual(params['q'], ['练习二'])
        response = self.client.get(f'/reviews/{self.future.pk}/'+self.query)
        self.assertEqual(response.url, '/reviews/'+self.query)
        self.assertEqual(self.client.get('/reviews/?q=不存在').context['remaining'], 0)

    def test_mismatched_or_foreign_scope_rejected_before_writing(self):
        for query in [f'?chapter={self.foreign_chapter.pk}', '?chapter=-1',
                      f'?course={self.second.pk}&chapter={self.root.pk}',
                      f'?chapter={self.root.pk}&point={self.sql_point.pk}']:
            self.assertEqual(self.client.get('/reviews/'+query).status_code, 404)
            self.assertEqual(self.save(self.first, query=query).status_code, 404)
        self.assertEqual(self.save(self.unrelated).status_code, 404)
        self.assertEqual(ReviewRecord.objects.count(), 0)

    def test_skip_all_is_not_completion_and_does_not_change_due_or_history(self):
        dates = list(WrongQuestion.objects.order_by('pk').values_list('pk', 'next_review_date'))
        self.assertEqual(self.client.get(f'/reviews/{self.first.pk}/skip/'+self.query).status_code, 405)
        response = self.client.post(f'/reviews/{self.first.pk}/skip/'+self.query)
        query = '?' + urlsplit(response.url).query
        self.assertEqual(urlsplit(response.url).path, f'/reviews/{self.next.pk}/')
        response = self.client.post(f'/reviews/{self.next.pk}/skip/'+query)
        self.assertEqual(urlsplit(response.url).path, '/reviews/')
        empty = self.client.get(response.url)
        self.assertContains(empty, '仍有 2 题待复习')
        self.assertNotContains(empty, '当前范围没有到期错题')
        self.assertEqual(empty.context['skipped_count'], 2)
        self.assertEqual(self.client.get(empty.context['scope_reset_url']).context['remaining'], 2)
        self.assertEqual(list(WrongQuestion.objects.order_by('pk').values_list('pk', 'next_review_date')), dates)
        self.assertFalse(ReviewRecord.objects.exists())
        repeated = self.client.post(f'/reviews/{self.next.pk}/skip/'+query, follow=True)
        self.assertEqual(repeated.context['skipped_count'], 2)

    def test_skip_then_save_last_reports_remaining_skipped(self):
        response = self.client.post(f'/reviews/{self.first.pk}/skip/'+self.query)
        query = '?' + urlsplit(response.url).query
        response = self.save(self.next, query=query)
        result = self.client.get(response.url)
        self.assertEqual(result.context['remaining'], 0)
        self.assertEqual(result.context['skipped_count'], 1)
        self.assertContains(result, '仍有 1 题待复习')
        # A second browser remains independent; the flow is not an authorization token.
        second = Client(); second.force_login(self.user)
        result = second.get('/reviews/'+query)
        self.assertEqual(result.context['remaining'], 1)
        self.assertContains(result, '暂时跳过记录已失效')

    def test_round_cannot_be_reused_for_another_scope_and_expiry_is_explicit(self):
        response = self.client.post(f'/reviews/{self.first.pk}/skip/'+self.query)
        token = parse_qs(urlsplit(response.url).query)['round'][0]
        self.assertEqual(self.client.get(f'/reviews/?chapter={self.outside.pk}&round={token}').status_code, 404)
        session = self.client.session
        state = session['review_rounds']; state[token]['created'] = 0
        session['review_rounds'] = state; session.save()
        response = self.client.get('/reviews/'+self.query+'&round='+token)
        self.assertEqual(response.context['remaining'], 2)
        self.assertContains(response, '暂时跳过记录已失效')

    def test_skip_requires_csrf_and_question_links_keep_filters(self):
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.user)
        self.assertEqual(csrf.post(f'/reviews/{self.first.pk}/skip/'+self.query).status_code, 403)
        response = self.client.get('/questions/'+self.query+'&review_status=due&q=练习')
        self.assertIn('chapter=', response.context['review_query'])
        self.assertIn('q=', response.context['review_query'])

    def test_invalid_answer_and_archived_course_keep_scope_without_writes(self):
        url = f'/reviews/{self.first.pk}/' + self.query
        token = services.make_token(self.user, 'review', self.first)
        response = self.client.post(url, {'action': 'reveal', 'answer': '', 'token': token})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '本轮复习范围')
        self.assertIn('chapter=', response.context['scope_queue_url'])
        self.assertFalse(response.context['revealed'])
        self.course.is_archived = True; self.course.save()
        empty = self.client.get('/reviews/' + self.query)
        self.assertEqual(empty.context['remaining'], 0)
        self.assertContains(empty, self.course.name)
        self.assertFalse(ReviewRecord.objects.exists())

    def test_browser_back_to_skipped_question_can_save_then_continue(self):
        response = self.client.post(f'/reviews/{self.first.pk}/skip/' + self.query)
        query = '?' + urlsplit(response.url).query
        response = self.client.get(f'/reviews/{self.first.pk}/' + query)
        self.assertTrue(response.context['has_next_question'])
        response = self.save(self.first, query=query)
        self.assertEqual(urlsplit(response.url).path, f'/reviews/{self.next.pk}/')
        page = self.client.get(response.url)
        self.assertEqual(page.context['skipped_count'], 0)
        self.assertEqual(page.context['remaining'], 1)

    def test_question_details_preserve_range_before_starting_review(self):
        response = self.client.get(f'/questions/{self.first.pk}/' + self.query)
        self.assertEqual(response.context['review_query'], self.query)
        self.assertEqual(response.context['scope_questions_url'], '/questions/' + self.query)
        self.assertContains(response, f'/reviews/{self.first.pk}/?course={self.course.pk}&amp;chapter={self.root.pk}')
        self.assertEqual(self.client.get(f'/questions/{self.unrelated.pk}/' + self.query).status_code, 404)

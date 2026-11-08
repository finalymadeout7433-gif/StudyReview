from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from learning import services
from learning.models import Course, Chapter, KnowledgePoint, WrongQuestion
from learning.question_variants import VARIANT_QUESTIONS


class TeammateVariantIntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('synthetic_variant_owner')
        self.other = get_user_model().objects.create_user('synthetic_variant_other')
        self.course = Course.objects.create(owner=self.user, name='Synthetic variant course')
        self.chapter = Chapter.objects.create(course=self.course, name='Synthetic chapter')
        self.point = KnowledgePoint.objects.create(course=self.course, chapter=self.chapter, name='Synthetic point')
        self.question = self.make_question(next(iter(VARIANT_QUESTIONS)))
        self.question.knowledge_points.add(self.point)
        self.url = reverse('question-variant', args=[self.question.pk])
        self.client.force_login(self.user)

    def make_question(self, title, course=None):
        return WrongQuestion.objects.create(course=course or self.course, title=title,
            content='Synthetic original prompt', original_answer='Synthetic original answer',
            correct_answer='Synthetic correct answer', error_reason='Synthetic reason',
            next_review_date=timezone.localdate())

    def test_all_22_variants_render_and_reveal_without_writing(self):
        self.assertEqual(len(VARIANT_QUESTIONS), 22)
        for title, variant in VARIANT_QUESTIONS.items():
            with self.subTest(title=title):
                question = self.make_question(title)
                url = reverse('question-variant', args=[question.pk])
                count = WrongQuestion.objects.count()
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context['revealed'])
                self.assertNotIn(variant['answer'], response.content.decode())
                response = self.client.post(url, {'answer': 'Synthetic attempt'})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['revealed'])
                self.assertTrue(response.context['save_token'])
                self.assertEqual(WrongQuestion.objects.count(), count)

    def test_save_inherits_course_points_and_date(self):
        response = self.client.post(self.url, {'answer': 'Synthetic attempt'})
        token = response.context['save_token']
        response = self.client.post(self.url, {'action': 'save', 'answer': 'Synthetic attempt', 'save_token': token})
        self.assertEqual(response.status_code, 302)
        saved = WrongQuestion.objects.exclude(pk=self.question.pk).get()
        self.assertEqual(saved.course, self.course)
        self.assertEqual(list(saved.knowledge_points.all()), [self.point])
        self.assertEqual(saved.original_answer, 'Synthetic attempt')
        self.assertEqual(saved.content, VARIANT_QUESTIONS[self.question.title]['prompt'])
        self.assertEqual(saved.next_review_date, timezone.localdate() + timedelta(days=1))
        self.assertEqual(saved.reviews.count(), 0)
        self.question.refresh_from_db()
        self.assertEqual(self.question.content, 'Synthetic original prompt')
        self.assertEqual(self.question.reviews.count(), 0)

    def test_duplicate_save_does_not_duplicate_question(self):
        token = self.client.post(self.url, {'answer': 'Synthetic attempt'}).context['save_token']
        data = {'action': 'save', 'answer': 'Synthetic attempt', 'save_token': token}
        first = self.client.post(self.url, data)
        second = self.client.post(self.url, data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(first.url, second.url)
        self.assertEqual(WrongQuestion.objects.count(), 2)

    def test_empty_answer_does_not_reveal(self):
        response = self.client.post(self.url, {'answer': '   '})
        self.assertFalse(response.context['revealed'])
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(WrongQuestion.objects.count(), 1)

    def test_missing_tampered_and_wrong_object_token_do_not_save(self):
        second = self.make_question(next(iter(VARIANT_QUESTIONS)))
        for token in ('', 'invalid', services.make_token(self.user, 'question-create', second)):
            with self.subTest(token_kind='invalid_or_wrong_object'):
                response = self.client.post(self.url, {'action': 'save', 'answer': 'Synthetic attempt', 'save_token': token})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['save_error'])
                self.assertEqual(WrongQuestion.objects.count(), 2)

    def test_other_user_cannot_access_or_post(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {'answer': 'attempt'}).status_code, 404)

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_archived_question_and_course_are_readonly(self):
        services.archive_question(self.user, self.question.pk, True)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {'answer': 'attempt'}).status_code, 404)
        services.archive_question(self.user, self.question.pk, False)
        services.archive_course(self.user, self.course.pk, True)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_question_without_variant_has_no_entry(self):
        question = self.make_question('No companion exercise')
        self.assertEqual(self.client.get(reverse('question-variant', args=[question.pk])).status_code, 404)
        response = self.client.get(reverse('question-detail', args=[question.pk]))
        self.assertNotContains(response, '练一道类似题')

    def test_local_assistant_and_scoped_navigation_are_preserved(self):
        response = self.client.get(reverse('question-detail', args=[self.question.pk]) + f'?course={self.course.pk}')
        self.assertContains(response, '练一道类似题')
        self.assertContains(response, '助手整理')
        self.assertContains(response, 'id="mi-launcher"')
        self.assertContains(response, f'/reviews/{self.question.pk}/?course={self.course.pk}')

    def test_unsupported_method_is_rejected(self):
        self.assertEqual(self.client.put(self.url).status_code, 405)

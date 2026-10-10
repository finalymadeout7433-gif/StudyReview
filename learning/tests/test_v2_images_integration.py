"""Real uploaded pixels through root forms, review atomic writes and local draft confirmation.

Run only against the explicitly isolated V2 attachment test database. No provider is
called, no real records are imported, and every image resides in a TemporaryDirectory.
"""
import io
import json
from pathlib import Path
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from attachments.models import Attachment, ImageRole, QuestionImage, ReviewImageManifest, ReviewImageSnapshot
from attachments.services import attachment_path
from assistant import services as assistant_services
from assistant.models import Draft
from learning import services
from learning.forms import QuestionForm
from learning.models import Course, KnowledgePoint, QuestionKnowledgePoint, ReviewRecord, WrongQuestion
from scheduling.models import ScheduleEvent, SchedulingState


@override_settings(ROOT_URLCONF='config.urls', PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class V2ImagesIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user('synthetic_v2_image_owner', password='Synthetic-Only-2026!')
        cls.other = User.objects.create_user('synthetic_v2_image_other', password='Synthetic-Only-2026!')
        cls.course = Course.objects.create(owner=cls.owner, name='合成图片整合课程')
        cls.other_course = Course.objects.create(owner=cls.other, name='其他人的合成课程')
        cls.point = KnowledgePoint.objects.create(course=cls.course, name='合成知识点')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='study-v2-images-integration-')
        self.media_settings = override_settings(PRIVATE_MEDIA_ROOT=Path(self.directory.name))
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)
        self.addCleanup(self.directory.cleanup)
        self.client.force_login(self.owner)
        self.image_number = 0

    def upload(self, *, owner=None, name=None):
        owner = owner or self.owner
        self.image_number += 1
        stream = io.BytesIO()
        with Image.new('RGB', (32, 20), (self.image_number, 70, 120)) as image:
            image.save(stream, format='PNG')
        uploaded = SimpleUploadedFile(name or f'合成试卷-{self.image_number}.png', stream.getvalue(), content_type='image/png')
        self.client.force_login(owner)
        response = self.client.post(reverse('attachments:upload'), {'file': uploaded})
        self.assertEqual(response.status_code, 201, response.content)
        result = response.json()
        self.assertEqual((result['width'], result['height']), (32, 20))
        self.assertNotIn('storage_key', result)
        attachment = Attachment.objects.get(pk=result['id'], owner=owner)
        with Image.open(attachment_path(attachment)) as saved:
            self.assertEqual(saved.size, (32, 20))
            self.assertEqual(saved.format, 'PNG')
        self.client.force_login(self.owner)
        return result

    def four_images(self):
        return {role: self.upload(name=f'合成-{role}.png') for role in ImageRole.values}

    def payload(self, images=None, **overrides):
        data = {'course': str(self.course.pk), 'title': '合成整合错题', 'content': '合成题干内容',
            'original_answer': '合成原答', 'correct_answer': '合成参考答案', 'error_reason': '合成错因',
            'next_review_date': timezone.localdate().isoformat(), 'knowledge_points': [str(self.point.pk)],
            'image_payload': json.dumps([{'id': image['id'], 'role': role} for role, image in (images or {}).items()])}
        data.update(overrides)
        return data

    def create_question(self, images=None):
        response = self.client.get(reverse('question-create'))
        self.assertEqual(response.status_code, 200)
        data = self.payload(images, token=response.context['form'].initial['token'])
        saved = self.client.post(reverse('question-create'), data)
        self.assertEqual(saved.status_code, 302, saved.content)
        return WrongQuestion.objects.get(creation_key=services.read_token(data['token'], self.owner, 'question-create')['key'])

    def values(self, question, groups, **changes):
        result = {'course': self.course, 'title': question.title, 'content': question.content,
            'original_answer': question.original_answer, 'correct_answer': question.correct_answer,
            'error_reason': question.error_reason, 'next_review_date': question.next_review_date,
            'knowledge_points': [self.point], 'image_groups': groups}
        result.update(changes)
        return result

    def image_ids(self, question):
        return {role: list(question.image_links.filter(role=role).order_by('position').values_list('attachment_id', flat=True))
            for role in ImageRole.values}

    def revealed(self, question):
        url = reverse('review-question', args=[question.pk])
        recall = self.client.get(url)
        self.assertEqual(recall.status_code, 200)
        response = self.client.post(url, {'action': 'reveal', 'answer': '合成独立尝试',
            'token': recall.context['form'].initial['token']})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['revealed'])
        return response.context['form'].initial['token']

    def review_token(self, question):
        question.refresh_from_db()
        return services.reveal_token(services.make_token(self.owner, 'review', question), self.owner, question)

    def assert_no_review_writes(self, question, expected_date):
        self.assertEqual(ReviewRecord.objects.count(), 0)
        self.assertEqual(ReviewImageManifest.objects.count(), 0)
        self.assertEqual(ReviewImageSnapshot.objects.count(), 0)
        self.assertEqual(SchedulingState.objects.count(), 0)
        self.assertEqual(ScheduleEvent.objects.count(), 0)
        question.refresh_from_db()
        self.assertEqual(question.next_review_date, expected_date)

    def draft_create_data(self, images):
        return {'operation': 'create_question', 'submission_key': str(uuid.uuid4()), 'payload': {
            'course_id': self.course.pk, 'title': '合成图片草稿', 'content': '合成草稿题干',
            'original_answer': '合成草稿原答', 'correct_answer': '合成草稿参考答案', 'error_reason': '合成草稿错因',
            'next_review_date': timezone.localdate().isoformat(), 'knowledge_point_ids': [self.point.pk],
            'attachment_ids': [image['id'] for image in images]}}

    def test_real_upload_question_form_binds_all_four_roles(self):
        images = self.four_images()
        form = QuestionForm(self.payload(images), user=self.owner)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['image_groups'], {role: [image['id']] for role, image in images.items()})
        question = self.create_question(images)
        expected = {role: [uuid.UUID(image['id'])] for role, image in images.items()}
        self.assertEqual(self.image_ids(question), expected)
        self.assertEqual(list(question.knowledge_points.values_list('pk', flat=True)), [self.point.pk])
        detail = self.client.get(reverse('question-detail', args=[question.pk]))
        self.assertEqual({image['id'] for image in detail.context['question_images']}, {image['id'] for image in images.values()})
        for image in images.values():
            self.assertContains(detail, image['url'])

    def test_recall_hides_answer_images_until_explicit_reveal(self):
        images = self.four_images()
        question = self.create_question(images)
        url = reverse('review-question', args=[question.pk])
        recall = self.client.get(url)
        self.assertFalse(recall.context['revealed'])
        self.assertEqual([image['role'] for image in recall.context['question_images']], ['question'])
        self.assertContains(recall, images['question']['url'])
        for role in ['original_answer', 'correct_answer', 'error_reason']:
            self.assertNotContains(recall, images[role]['url'])
            self.assertNotContains(recall, images[role]['thumbnail_url'])
        self.assertNotContains(recall, '合成参考答案')
        revealed = self.client.post(url, {'action': 'reveal', 'answer': '合成独立尝试',
            'token': recall.context['form'].initial['token']})
        self.assertTrue(revealed.context['revealed'])
        self.assertEqual({image['role'] for image in revealed.context['question_images']}, set(ImageRole.values))
        for image in images.values():
            self.assertContains(revealed, image['url'])
        self.assertContains(revealed, '合成参考答案')
        self.assertEqual(ReviewRecord.objects.count(), 0)
        self.assertEqual(SchedulingState.objects.count(), 0)

    def test_invalid_reveal_token_does_not_expose_answer_images(self):
        images = self.four_images()
        question = self.create_question(images)
        response = self.client.post(reverse('review-question', args=[question.pk]),
            {'action': 'reveal', 'answer': '合成独立尝试', 'token': 'tampered-synthetic-token'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['revealed'])
        self.assertEqual([image['role'] for image in response.context['question_images']], ['question'])
        self.assertContains(response, images['question']['url'])
        for role in ['original_answer', 'correct_answer', 'error_reason']:
            self.assertNotContains(response, images[role]['url'])
        self.assert_no_review_writes(question, timezone.localdate())

    def test_review_freezes_images_and_edit_preserves_readable_old_history(self):
        images = self.four_images()
        question = self.create_question(images)
        token = self.revealed(question)
        saved = self.client.post(reverse('review-question', args=[question.pk]), {'action': 'save',
            'answer': '合成独立尝试', 'rating': 'good', 'note': '合成复习备注', 'token': token})
        self.assertEqual(saved.status_code, 302)
        record = question.reviews.get()
        frozen = list(record.image_snapshots.values_list('role', 'attachment_id', 'name_snapshot', 'sha256_snapshot'))
        self.assertEqual(len(frozen), 4)
        self.assertEqual(record.image_manifest.image_count, 4)
        self.assertEqual(SchedulingState.objects.get(question=question).revision, 1)
        self.assertEqual(ScheduleEvent.objects.get(review_record=record).state_revision_after, 1)
        new_image = self.upload(name='合成新题干.png')
        question.refresh_from_db()
        edited = self.client.post(reverse('question-edit', args=[question.pk]), self.payload({'question': new_image},
            next_review_date=question.next_review_date.isoformat(), correct_answer='新版合成参考答案'))
        self.assertEqual(edited.status_code, 302, edited.content)
        question.refresh_from_db()
        self.assertEqual(question.correct_answer, '新版合成参考答案')
        self.assertEqual(self.image_ids(question)['question'], [uuid.UUID(new_image['id'])])
        self.assertEqual(question.image_links.count(), 1)
        record.refresh_from_db()
        self.assertEqual(record.correct_answer_snapshot, '合成参考答案')
        self.assertEqual(list(record.image_snapshots.values_list('role', 'attachment_id', 'name_snapshot', 'sha256_snapshot')), frozen)
        detail = self.client.get(reverse('question-detail', args=[question.pk]))
        self.assertContains(detail, new_image['url'])
        for image in images.values():
            self.assertContains(detail, image['url'])
            media = self.client.get(image['url'])
            self.assertEqual(media.status_code, 200)
            self.assertTrue(b''.join(media.streaming_content).startswith(b'\x89PNG'))

    def test_review_save_replay_keeps_one_snapshot_set_and_one_schedule_event(self):
        image = self.upload()
        question = self.create_question({'question': image})
        token = self.revealed(question)
        data = {'action': 'save', 'answer': '合成独立尝试', 'rating': 'good', 'token': token}
        for _ in range(2):
            self.assertEqual(self.client.post(reverse('review-question', args=[question.pk]), data).status_code, 302)
        self.assertEqual(ReviewRecord.objects.count(), 1)
        self.assertEqual(ReviewImageManifest.objects.count(), 1)
        self.assertEqual(ReviewImageSnapshot.objects.count(), 1)
        self.assertEqual(ScheduleEvent.objects.count(), 1)
        self.assertEqual(SchedulingState.objects.get(question=question).revision, 1)

    def test_manual_date_is_saved_and_truthfully_labeled_in_image_history(self):
        image = self.upload()
        question = self.create_question({'question': image})
        token = self.revealed(question)
        chosen = timezone.localdate() + timedelta(days=12)
        response = self.client.post(reverse('review-question', args=[question.pk]), {
            'action': 'save', 'answer': '合成独立尝试', 'rating': 'good', 'token': token,
            'next_review_date': chosen.isoformat()})
        self.assertEqual(response.status_code, 302)
        record = question.reviews.get()
        event = ScheduleEvent.objects.get(review_record=record)
        self.assertEqual(event.manual_override_date, chosen)
        self.assertEqual(event.applied_date, chosen)
        self.assertEqual(record.next_review_date, chosen)
        question.refresh_from_db()
        self.assertEqual(question.next_review_date, chosen)
        self.assertEqual(record.image_snapshots.get().attachment_id, uuid.UUID(image['id']))
        detail = self.client.get(reverse('question-detail', args=[question.pk]))
        self.assertContains(detail, '使用自选日期')
        self.assertNotContains(detail, '使用算法建议')

    def test_image_change_invalidates_review_even_without_timestamp_change(self):
        old = self.upload()
        question = self.create_question({'question': old})
        initial = services.make_token(self.owner, 'review', question)
        revealed = services.reveal_token(initial, self.owner, question)
        old_timestamp = question.updated_at
        replacement = self.upload()
        QuestionImage.objects.filter(question=question, role='question').update(attachment_id=replacement['id'])
        question.refresh_from_db()
        self.assertEqual(question.updated_at, old_timestamp)
        with self.assertRaises(ValidationError):
            services.reveal_token(initial, self.owner, question)
        with self.assertRaises(ValidationError):
            services.submit_review(self.owner, question.pk, {'answer': '合成尝试', 'rating': 'good'}, revealed)
        self.assert_no_review_writes(question, timezone.localdate())

    def test_foreign_image_on_last_role_rolls_back_question_creation(self):
        own = self.upload()
        foreign = self.upload(owner=self.other)
        groups = {role: [own['id']] for role in ImageRole.values}
        groups['error_reason'] = [foreign['id']]
        values = {'course': self.course, 'title': '必须整体回滚', 'content': '题干', 'original_answer': '原答',
            'correct_answer': '答案', 'error_reason': '错因', 'next_review_date': timezone.localdate(),
            'knowledge_points': [self.point], 'image_groups': groups}
        with self.assertRaises(Http404):
            services.save_question(self.owner, values, token=services.make_token(self.owner, 'question-create'))
        self.assertEqual(WrongQuestion.objects.count(), 0)
        self.assertEqual(QuestionImage.objects.count(), 0)
        self.assertEqual(QuestionKnowledgePoint.objects.count(), 0)
        self.assertEqual(Attachment.objects.count(), 2)

    def test_foreign_image_on_last_role_rolls_back_text_points_and_prior_roles(self):
        images = self.four_images()
        question = self.create_question(images)
        before = self.image_ids(question)
        old_timestamp = question.updated_at
        own = self.upload()
        foreign = self.upload(owner=self.other)
        groups = {role: [own['id']] for role in ImageRole.values}
        groups['error_reason'] = [foreign['id']]
        with self.assertRaises(Http404):
            services.save_question(self.owner, self.values(question, groups, title='失败的新标题', knowledge_points=[]), pk=question.pk)
        question.refresh_from_db()
        self.assertEqual(question.title, '合成整合错题')
        self.assertEqual(question.updated_at, old_timestamp)
        self.assertEqual(self.image_ids(question), before)
        self.assertEqual(list(question.knowledge_points.values_list('pk', flat=True)), [self.point.pk])

    def test_snapshot_schedule_and_final_question_failures_each_roll_back_entire_review(self):
        question = self.create_question(self.four_images())
        expected_date = question.next_review_date
        for location in ['attachments.services.ReviewImageSnapshot.objects.bulk_create',
                         'scheduling.services.ScheduleEvent.save', 'learning.services.WrongQuestion.save']:
            token = self.review_token(question)
            with self.subTest(failure_after=location), patch(location, side_effect=RuntimeError('synthetic failure')):
                with self.assertRaises(RuntimeError):
                    services.submit_review(self.owner, question.pk, {'answer': '合成独立尝试', 'rating': 'good'}, token)
            self.assert_no_review_writes(question, expected_date)
            self.assertEqual(question.image_links.count(), 4)

    def test_cross_owner_read_and_archived_write_leave_images_intact(self):
        images = self.four_images()
        question = self.create_question(images)
        token = self.review_token(question)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('question-detail', args=[question.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('review-question', args=[question.pk])).status_code, 404)
        self.assertEqual(self.client.get(images['question']['url']).status_code, 404)
        self.client.force_login(self.owner)
        for archive_course in [True, False]:
            if archive_course:
                services.archive_course(self.owner, self.course.pk, True)
            else:
                services.archive_course(self.owner, self.course.pk, False)
                services.archive_question(self.owner, question.pk, True)
            with self.subTest(course_archived=archive_course):
                with self.assertRaises(ValidationError):
                    services.save_question(self.owner, self.values(question, {role: [] for role in ImageRole.values}), pk=question.pk)
                with self.assertRaises(ValidationError):
                    services.submit_review(self.owner, question.pk, {'answer': '合成尝试', 'rating': 'good'}, token)
                self.assertEqual(self.client.get(reverse('question-edit', args=[question.pk])).status_code, 403)
                self.assertEqual(question.image_links.count(), 4)
        self.assert_no_review_writes(question, timezone.localdate())

    def test_question_create_replay_cannot_replace_first_submission_images(self):
        first_image = self.upload()
        second_image = self.upload()
        create = self.client.get(reverse('question-create'))
        token = create.context['form'].initial['token']
        first = self.client.post(reverse('question-create'), self.payload({'question': first_image}, token=token))
        second = self.client.post(reverse('question-create'), self.payload({'question': second_image}, token=token, title='重放的新标题'))
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        question = WrongQuestion.objects.get()
        self.assertEqual(question.title, '合成整合错题')
        self.assertEqual(self.image_ids(question)['question'], [uuid.UUID(first_image['id'])])

    def test_local_image_draft_requires_confirmation_and_duplicate_confirm_is_harmless(self):
        images = [self.upload(), self.upload()]
        session, _ = assistant_services.create_session(self.owner, '合成图片草稿会话', uuid.uuid4())
        draft, created = assistant_services.create_draft(self.owner, session.pk, self.draft_create_data(images))
        self.assertTrue(created)
        self.assertEqual(WrongQuestion.objects.count(), 0)
        self.assertEqual(draft.status, Draft.Status.PENDING)
        token = assistant_services.confirmation_token(draft)
        key = uuid.uuid4()
        applied, first = assistant_services.confirm_draft(self.owner, draft.pk, token, key)
        replay, second = assistant_services.confirm_draft(self.owner, draft.pk, token, key)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(applied.applied_object_id, replay.applied_object_id)
        question = WrongQuestion.objects.get(pk=applied.applied_object_id)
        self.assertEqual(self.image_ids(question)['question'], [uuid.UUID(image['id']) for image in images])
        self.assertEqual(WrongQuestion.objects.count(), 1)
        self.assertEqual(QuestionImage.objects.count(), 2)

    def test_draft_image_link_failure_keeps_pending_draft_and_no_partial_question(self):
        image = self.upload()
        session, _ = assistant_services.create_session(self.owner, '合成故障草稿', uuid.uuid4())
        draft, _ = assistant_services.create_draft(self.owner, session.pk, self.draft_create_data([image]))
        with patch('assistant.services.sync_question_images', side_effect=RuntimeError('synthetic link failure')):
            with self.assertRaises(RuntimeError):
                assistant_services.confirm_draft(self.owner, draft.pk, assistant_services.confirmation_token(draft), uuid.uuid4())
        draft.refresh_from_db()
        self.assertEqual(draft.status, Draft.Status.PENDING)
        self.assertIsNone(draft.applied_object_id)
        self.assertIsNone(draft.confirmation_key)
        self.assertEqual(WrongQuestion.objects.count(), 0)
        self.assertEqual(QuestionImage.objects.count(), 0)
        self.assertEqual(QuestionKnowledgePoint.objects.count(), 0)
        self.assertTrue(attachment_path(Attachment.objects.get(pk=image['id'])).exists())

    def test_answer_image_edit_invalidates_pending_question_draft(self):
        images = self.four_images()
        question = self.create_question(images)
        replacement = self.upload()
        session, _ = assistant_services.create_session(self.owner, '合成版本草稿', uuid.uuid4())
        preview = assistant_services.target_preview(self.owner, 'question', question.pk)
        draft, _ = assistant_services.create_draft(self.owner, session.pk, {
            'operation': 'update_question', 'target_id': question.pk,
            'expected_version': preview['expected_version'], 'submission_key': str(uuid.uuid4()),
            'payload': {'title': '旧草稿标题'}})
        groups = {role: [image['id']] for role, image in images.items()}
        groups['correct_answer'] = [replacement['id']]
        services.save_question(self.owner, self.values(question, groups), pk=question.pk)
        with self.assertRaises(assistant_services.Conflict):
            assistant_services.confirm_draft(self.owner, draft.pk, assistant_services.confirmation_token(draft), uuid.uuid4())
        question.refresh_from_db()
        self.assertEqual(question.title, '合成整合错题')
        self.assertEqual(self.image_ids(question)['correct_answer'], [uuid.UUID(replacement['id'])])
        draft.refresh_from_db()
        self.assertEqual(draft.status, Draft.Status.PENDING)

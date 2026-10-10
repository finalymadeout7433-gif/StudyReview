import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import uuid
from unittest.mock import patch
import zlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from PIL import Image, PngImagePlugin, features
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.uploadhandler import StopUpload
from django.db import DatabaseError, IntegrityError, connection, connections, transaction
from django.http import Http404
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from learning.models import Course, WrongQuestion, ReviewRecord
from attachments.models import Attachment, ImageRole, QuestionImage, ReviewImageManifest, ReviewImageSnapshot
from attachments.services import (MAX_INPUT_BYTES, attachment_path, owned_attachment,
    upload_attachment, sync_question_images, snapshot_question_images)
from attachments.upload_handlers import ImageUploadLimitHandler, ImageUploadLimitMiddleware, MAX_REQUEST_BYTES


def image_file(name='试卷.png', format='PNG', size=(18, 12), color=(255, 255, 255), **options):
    with Image.new('RGB', size, color) as image:
        target = io.BytesIO()
        image.save(target, format=format, **options)
    mime = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp', 'GIF': 'image/gif'}[format]
    return SimpleUploadedFile(name, target.getvalue(), content_type=mime)


def header_only_png(width, height):
    def chunk(kind, content):
        return struct.pack('!I', len(content)) + kind + content + struct.pack('!I', zlib.crc32(kind + content))
    data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', width, height, 8, 2, 0, 0, 0))
    data += chunk(b'IDAT', zlib.compress(b'\x00')) + chunk(b'IEND', b'')
    return SimpleUploadedFile('too-large.png', data, content_type='image/png')


@override_settings(ROOT_URLCONF='attachments.tests.urls', PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AttachmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user('attachment_owner', password='Synthetic-Only-2026!')
        cls.other = User.objects.create_user('attachment_other', password='Synthetic-Only-2026!')
        cls.course = Course.objects.create(owner=cls.owner, name='附件测试课程')
        cls.other_course = Course.objects.create(owner=cls.other, name='其他人的课程')
        cls.question = WrongQuestion.objects.create(course=cls.course, title='附件测试错题', content='题干', original_answer='原答',
            correct_answer='参考答案', error_reason='错因', next_review_date=timezone.localdate())
        cls.other_question = WrongQuestion.objects.create(course=cls.other_course, title='其他人的错题', content='私有题干', original_answer='原答',
            correct_answer='参考答案', error_reason='错因', next_review_date=timezone.localdate())

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='study-attachment-tests-')
        self.settings_context = override_settings(PRIVATE_MEDIA_ROOT=Path(self.directory.name))
        self.settings_context.enable()
        self.addCleanup(self.settings_context.disable)
        self.addCleanup(self.directory.cleanup)
        self.client.force_login(self.owner)

    def make_review(self, question=None):
        question = question or self.question
        today = timezone.localdate()
        from datetime import timedelta
        return ReviewRecord.objects.create(question=question, review_date=today, answer='合成回答', rating='good',
            next_review_date=today + timedelta(days=7), title_snapshot=question.title, question_snapshot=question.content,
            original_answer_snapshot=question.original_answer, correct_answer_snapshot=question.correct_answer,
            error_reason_snapshot=question.error_reason, course_snapshot=question.course.name,
            submission_key=uuid.uuid4())

    def test_png_is_full_resolution_and_has_separate_thumbnail(self):
        attachment = upload_attachment(self.owner, image_file(size=(1300, 850)))
        self.assertEqual((attachment.width, attachment.height), (1300, 850))
        with Image.open(attachment_path(attachment)) as saved:
            self.assertEqual(saved.size, (1300, 850))
            self.assertEqual(saved.format, 'PNG')
        with Image.open(attachment_path(attachment, thumbnail=True)) as thumbnail:
            self.assertEqual(thumbnail.width, 720)
            self.assertLessEqual(thumbnail.height, 720)
        self.assertEqual(attachment.byte_size, attachment_path(attachment).stat().st_size)

    def test_jpeg_orientation_applied_and_all_metadata_removed(self):
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = 'synthetic private artist'
        exif[270] = 'synthetic private description'
        attachment = upload_attachment(self.owner, image_file('scan.jpg', format='JPEG', size=(20, 30), exif=exif))
        self.assertEqual((attachment.width, attachment.height), (30, 20))
        with Image.open(attachment_path(attachment)) as saved:
            self.assertEqual(dict(saved.getexif()), {})
            self.assertEqual(saved.info, {})

    def test_png_text_metadata_removed(self):
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('Comment', '<script>synthetic only</script>')
        attachment = upload_attachment(self.owner, image_file(pnginfo=metadata))
        with Image.open(attachment_path(attachment)) as saved:
            self.assertEqual(saved.info, {})

    def test_static_webp_supported(self):
        if not features.check('webp'):
            self.skipTest('Pillow build has no WebP support')
        attachment = upload_attachment(self.owner, image_file('scan.webp', format='WEBP'))
        with Image.open(attachment_path(attachment)) as saved:
            self.assertEqual(saved.format, 'PNG')

    def test_transparency_preserved(self):
        image = Image.new('RGBA', (12, 10), (12, 22, 32, 40))
        target = io.BytesIO()
        image.save(target, format='PNG')
        attachment = upload_attachment(self.owner, SimpleUploadedFile('transparent.png', target.getvalue(), content_type='image/png'))
        with Image.open(attachment_path(attachment)) as saved:
            self.assertEqual(saved.getpixel((0, 0)), (12, 22, 32, 40))

    def test_same_normalized_content_deduplicates_per_owner(self):
        first = upload_attachment(self.owner, image_file('first.png'))
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('Secret', 'synthetic only')
        duplicate = upload_attachment(self.owner, image_file('second.png', pnginfo=metadata))
        self.assertEqual(first.pk, duplicate.pk)
        other = upload_attachment(self.other, image_file('same.png'))
        self.assertNotEqual(first.pk, other.pk)
        self.assertEqual(Attachment.objects.count(), 2)

    def test_display_name_cannot_be_storage_path_or_markup(self):
        attachment = upload_attachment(self.owner, image_file('C:\\unsafe\\<script>\u202eevil.png'))
        self.assertNotIn('\\', attachment.display_name)
        self.assertNotIn('<', attachment.display_name)
        self.assertNotIn('\u202e', attachment.display_name)
        self.assertNotIn('script', attachment.storage_key)
        self.assertTrue(attachment_path(attachment).is_relative_to(Path(self.directory.name)))

    def test_fake_mime_and_non_images_rejected(self):
        jpeg = image_file(format='JPEG')
        png = image_file()
        attempts = [SimpleUploadedFile('fake.png', jpeg.read(), content_type='image/png'),
            SimpleUploadedFile('script.svg', b'<svg><script>alert(1)</script></svg>', content_type='image/png'),
            SimpleUploadedFile('text.png', b'plain text', content_type='image/png'),
            SimpleUploadedFile('empty.png', b'', content_type='image/png'),
            SimpleUploadedFile('image.png', png.read(), content_type='text/html'), image_file(format='GIF')]
        for uploaded in attempts:
            with self.subTest(name=uploaded.name), self.assertRaises(ValidationError):
                upload_attachment(self.owner, uploaded)
        self.assertEqual(Attachment.objects.count(), 0)

    def test_animated_png_and_webp_rejected(self):
        for format in ['PNG', 'WEBP']:
            if format == 'WEBP' and not features.check('webp'):
                continue
            first = Image.new('RGB', (10, 10), 'white')
            second = Image.new('RGB', (10, 10), 'black')
            target = io.BytesIO()
            first.save(target, format=format, save_all=True, append_images=[second], duration=100, loop=0)
            mime = 'image/png' if format == 'PNG' else 'image/webp'
            with self.subTest(format=format), self.assertRaises(ValidationError):
                upload_attachment(self.owner, SimpleUploadedFile('animated', target.getvalue(), content_type=mime))

    def test_truncated_image_rejected(self):
        original = image_file().read()
        with self.assertRaises(ValidationError):
            upload_attachment(self.owner, SimpleUploadedFile('broken.png', original[:len(original)//2], content_type='image/png'))

    def test_pixel_and_dimension_limits_checked_before_decode(self):
        for dimensions in [(6000, 4000), (10001, 1)]:
            with self.subTest(dimensions=dimensions), self.assertRaises(ValidationError):
                upload_attachment(self.owner, header_only_png(*dimensions))
        self.assertEqual(Attachment.objects.count(), 0)

    def test_input_size_actual_bytes_and_declared_size_checked(self):
        oversized = SimpleUploadedFile('large.png', b'x' * (MAX_INPUT_BYTES + 1), content_type='image/png')
        with self.assertRaises(ValidationError):
            upload_attachment(self.owner, oversized)
        oversized.size = 1
        with self.assertRaises(ValidationError):
            upload_attachment(self.owner, oversized)

    def test_output_size_limit_rejects_without_partial_file(self):
        with patch('attachments.services.MAX_OUTPUT_BYTES', 16), self.assertRaises(ValidationError):
            upload_attachment(self.owner, image_file())
        self.assertEqual(Attachment.objects.count(), 0)
        self.assertEqual(list(Path(self.directory.name).rglob('*.png')), [])

    def test_upload_cannot_be_nested_in_business_transaction(self):
        with transaction.atomic():
            with self.assertRaises(RuntimeError):
                upload_attachment(self.owner, image_file())
        self.assertEqual(Attachment.objects.count(), 0)
        self.assertEqual(list(Path(self.directory.name).rglob('*.png')), [])

    def test_quota_counts_full_and_thumbnail_and_dedupe_needs_no_space(self):
        first = upload_attachment(self.owner, image_file())
        total = first.byte_size + first.thumbnail_bytes
        with override_settings(ATTACHMENT_USER_QUOTA_BYTES=total):
            self.assertEqual(upload_attachment(self.owner, image_file()).pk, first.pk)
            with self.assertRaises(ValidationError):
                upload_attachment(self.owner, image_file(color=(1, 2, 3)))
        self.assertEqual(Attachment.objects.count(), 1)

    def test_db_failure_cleans_both_new_files(self):
        with patch.object(Attachment, 'save', side_effect=IntegrityError('synthetic write failure')):
            with self.assertRaises(IntegrityError):
                upload_attachment(self.owner, image_file())
        self.assertEqual(Attachment.objects.count(), 0)
        self.assertEqual(list(Path(self.directory.name).rglob('*.png')), [])
        self.assertEqual(list(Path(self.directory.name).rglob('.pending-*')), [])

    def test_file_write_failure_leaves_no_attachment_or_partial_image(self):
        from attachments import services
        original = services._write_file
        calls = 0
        def fail_second(path, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('synthetic disk failure')
            original(path, data)
        with patch('attachments.services._write_file', side_effect=fail_second), self.assertRaises(OSError):
            upload_attachment(self.owner, image_file())
        self.assertEqual(Attachment.objects.count(), 0)
        self.assertEqual(list(Path(self.directory.name).rglob('*.png')), [])

    def test_path_traversal_rejected_for_corrupted_storage_key(self):
        for key in ['../outside', 'aa/../../outside', '/absolute', 'aa/' + 'b'*32]:
            fake = Attachment(storage_key=key)
            with self.subTest(key=key), self.assertRaises(ValidationError):
                attachment_path(fake)

    def test_symlink_storage_rejected_when_platform_allows_link(self):
        attachment = upload_attachment(self.owner, image_file())
        image_path = attachment_path(attachment)
        original = image_path.read_bytes()
        image_path.unlink()
        outside = Path(self.directory.name) / 'outside.png'
        outside.write_bytes(original)
        try:
            image_path.symlink_to(outside)
        except OSError as error:
            image_path.write_bytes(original)
            if os.name == 'nt' and getattr(error, 'winerror', None) == 1314:
                self.skipTest('Actual Windows file symlink creation denied: WinError 1314 (required privilege not held); junction tests are independent.')
            raise
        with self.assertRaises(ValidationError):
            attachment_path(attachment)

    def test_real_windows_directory_junctions_are_rejected_and_targets_preserved(self):
        if os.name != 'nt':
            self.skipTest('Actual Windows directory junction verification requires Windows.')
        if not hasattr(Path('.'), 'is_junction'):
            self.fail('This Windows interpreter cannot distinguish junctions; the service must be reviewed.')
        workspace = Path(tempfile.gettempdir()).resolve()
        self.assertTrue(workspace.is_dir())
        probe = workspace / 'junction-verification' / uuid.uuid4().hex
        probe.mkdir(parents=True, exist_ok=False)
        media = probe / 'media'
        outside = probe / 'outside-synthetic'
        media.mkdir()
        outside.mkdir()
        marker = outside / 'preserve-target.txt'
        marker.write_text('Synthetic target must survive unlinking junctions.', encoding='utf-8')
        powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
        self.assertTrue(powershell.is_file())
        created_links = []
        cases = []

        def create_junction(link, target):
            self.assertTrue(link.parent.resolve().is_relative_to(probe.resolve()))
            self.assertFalse(os.path.lexists(link))
            self.assertTrue(target.resolve().is_relative_to(probe.resolve()))
            environment = os.environ.copy()
            environment['STUDY_JUNCTION_LINK'] = str(link)
            environment['STUDY_JUNCTION_TARGET'] = str(target)
            script = "$ErrorActionPreference = 'Stop'\nNew-Item -ItemType Junction -Path $env:STUDY_JUNCTION_LINK -Target $env:STUDY_JUNCTION_TARGET | Out-Null"
            result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', script],
                env=environment, capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(link.is_junction(), 'The probe must create a real NTFS junction, not a mocked path.')
            self.assertEqual(link.resolve(), target.resolve())
            created_links.append((link, target))

        try:
            with override_settings(PRIVATE_MEDIA_ROOT=media):
                attachment = upload_attachment(self.owner, image_file('synthetic-junction.png'))
                original_full = attachment_path(attachment).read_bytes()
                original_thumbnail = attachment_path(attachment, thumbnail=True).read_bytes()
                mirror = outside.joinpath(*attachment.storage_key.split('/'))
                mirror.mkdir(parents=True)
                (mirror / 'full.png').write_bytes(original_full)
                (mirror / 'thumbnail.png').write_bytes(original_thumbnail)
            root_link = probe / 'media-root-junction'
            create_junction(root_link, outside)
            with override_settings(PRIVATE_MEDIA_ROOT=root_link):
                for thumbnail in [False, True]:
                    with self.subTest(location='private-root', thumbnail=thumbnail), self.assertRaises(ValidationError):
                        attachment_path(attachment, thumbnail=thumbnail)
                with self.assertRaises(ValidationError):
                    upload_attachment(self.owner, image_file(color=(2, 3, 4)))
                for route in ['attachments:media', 'attachments:thumbnail']:
                    self.assertEqual(self.client.get(reverse(route, kwargs={'attachment_id': attachment.pk})).status_code, 404)
            cases.append('Actual junction used as PRIVATE_MEDIA_ROOT rejected for path, upload and authorized media GET.')
            nested_uuid = uuid.uuid4().hex
            while (media / nested_uuid[:2]).exists():
                nested_uuid = uuid.uuid4().hex
            nested_link = media / nested_uuid[:2]
            create_junction(nested_link, outside)
            fake = Attachment(storage_key=f'{nested_uuid[:2]}/{nested_uuid}')
            with override_settings(PRIVATE_MEDIA_ROOT=media):
                for thumbnail in [False, True]:
                    with self.subTest(location='storage-shard', thumbnail=thumbnail), self.assertRaises(ValidationError):
                        attachment_path(fake, thumbnail=thumbnail)
            cases.append('Actual storage-shard junction resolving outside private root rejected for full and thumbnail paths.')
            self.assertEqual(Attachment.objects.count(), 1)
            self.assertEqual((mirror / 'full.png').read_bytes(), original_full)
            self.assertEqual((mirror / 'thumbnail.png').read_bytes(), original_thumbnail)
        finally:
            for link, target in reversed(created_links):
                # rmdir invokes RemoveDirectory on the exact junction entry. Never recurse
                # or resolve the link into its target before deleting the directory entry.
                self.assertTrue(link.parent.resolve().is_relative_to(probe.resolve()))
                self.assertTrue(link.is_junction(), 'Changed links are preserved for manual inspection.')
                self.assertEqual(link.resolve(), target.resolve())
                link.rmdir()
                self.assertFalse(os.path.lexists(link))
                self.assertTrue(target.is_dir())
            self.assertEqual(marker.read_text(encoding='utf-8'), 'Synthetic target must survive unlinking junctions.')
        report = {'platform': 'Windows', 'probe_root': str(probe), 'actual_junctions_created': len(created_links),
            'junction_entries_removed_without_recursion': True, 'outside_target_preserved': marker.is_file(),
            'file_symlink_claimed_verified': False, 'system_security_settings_changed': False, 'cases': cases}
        (probe / 'evidence.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_attachment_is_immutable_and_cross_owner_is_404(self):
        attachment = upload_attachment(self.owner, image_file())
        self.assertEqual(owned_attachment(self.owner, attachment.pk).pk, attachment.pk)
        with self.assertRaises(Http404):
            owned_attachment(self.other, attachment.pk)
        with self.assertRaises(Http404):
            owned_attachment(self.owner, 'not-a-uuid')
        with self.assertRaises(ValidationError):
            attachment.save()
        with self.assertRaises(ValidationError):
            Attachment.objects.filter(pk=attachment.pk).update(display_name='changed')
        with self.assertRaises(ValidationError):
            attachment.delete()

    def test_media_is_authorized_png_and_private_without_storage_disclosure(self):
        attachment = upload_attachment(self.owner, image_file())
        for name in ['attachments:media', 'attachments:thumbnail']:
            url = reverse(name, kwargs={'attachment_id': attachment.pk})
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/png')
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(response['Cross-Origin-Resource-Policy'], 'same-origin')
            self.assertNotIn(attachment.storage_key, str(dict(response.headers)))
            self.assertTrue(b''.join(response.streaming_content).startswith(b'\x89PNG'))
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(url).status_code, 404)
            self.client.force_login(self.owner)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_missing_media_returns_404(self):
        attachment = upload_attachment(self.owner, image_file())
        attachment_path(attachment).unlink()
        self.assertEqual(self.client.get(reverse('attachments:media', kwargs={'attachment_id': attachment.pk})).status_code, 404)

    def test_upload_http_returns_safe_json(self):
        response = self.client.post(reverse('attachments:upload'), {'file': image_file()})
        self.assertEqual(response.status_code, 201)
        result = response.json()
        self.assertEqual(set(result), {'id', 'url', 'thumbnail_url', 'name', 'width', 'height'})
        media_response = self.client.get(result['url'])
        self.assertEqual(media_response.status_code, 200)
        self.assertTrue(b''.join(media_response.streaming_content).startswith(b'\x89PNG'))
        self.assertNotIn('storage_key', result)

    def test_upload_rejects_wrong_method_multiple_files_and_invalid_data(self):
        url = reverse('attachments:upload')
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {}).status_code, 400)
        response = self.client.post(url, {'file': SimpleUploadedFile('fake.png', b'bad', content_type='image/png')})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(url, {'file': [image_file(), image_file()]})
        self.assertIn(response.status_code, [400, 413])
        self.assertEqual(Attachment.objects.count(), 0)

    def test_upload_requires_csrf_even_for_logged_in_user(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        response = client.post(reverse('attachments:upload'), {'file': image_file()})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Attachment.objects.count(), 0)

    def test_upload_storage_or_database_failure_is_safe_readable_json(self):
        for failure in [OSError('synthetic private path detail'), DatabaseError('synthetic private database detail')]:
            with self.subTest(error=type(failure).__name__), patch('attachments.views.upload_attachment', side_effect=failure):
                response = self.client.post(reverse('attachments:upload'), {'file': image_file()})
                self.assertEqual(response.status_code, 503)
                self.assertIn('稍后重试', response.json()['error'])
                self.assertNotIn('synthetic private', response.content.decode())

    def test_question_images_replace_order_and_touch_version(self):
        first = upload_attachment(self.owner, image_file(color=(1, 2, 3)))
        second = upload_attachment(self.owner, image_file(color=(4, 5, 6)))
        before = self.question.updated_at
        links = sync_question_images(self.owner, self.question, [str(second.pk), str(first.pk)])
        self.assertEqual([link.attachment_id for link in links], [second.pk, first.pk])
        self.question.refresh_from_db()
        self.assertGreater(self.question.updated_at, before)
        same_version = self.question.updated_at
        sync_question_images(self.owner, self.question, [second.pk, first.pk])
        self.question.refresh_from_db()
        self.assertEqual(self.question.updated_at, same_version)
        sync_question_images(self.owner, self.question, [first.pk])
        self.assertEqual(list(self.question.image_links.values_list('attachment_id', flat=True)), [first.pk])
        sync_question_images(self.owner, self.question, [])
        self.assertEqual(self.question.image_links.count(), 0)
        self.assertEqual(Attachment.objects.count(), 2)

    def test_ownership_validation_precedes_any_unlink(self):
        own = upload_attachment(self.owner, image_file())
        foreign = upload_attachment(self.other, image_file())
        sync_question_images(self.owner, self.question, [own.pk])
        for identifiers in [[foreign.pk], [own.pk, uuid.uuid4()]]:
            with self.subTest(ids=identifiers), self.assertRaises(Http404):
                sync_question_images(self.owner, self.question, identifiers)
        with self.assertRaises(Http404):
            sync_question_images(self.owner, self.other_question, [own.pk])
        self.assertEqual(self.question.image_links.get().attachment_id, own.pk)

    def test_role_duplicate_count_and_archive_rules(self):
        attachment = upload_attachment(self.owner, image_file())
        for identifiers, role in [([attachment.pk], 'invalid'), ([attachment.pk, attachment.pk], 'question'), ('not-a-list', 'question')]:
            with self.subTest(role=role), self.assertRaises(ValidationError):
                sync_question_images(self.owner, self.question, identifiers, role=role)
        with override_settings(ATTACHMENT_MAX_PER_ROLE=1), self.assertRaises(ValidationError):
            sync_question_images(self.owner, self.question, [attachment.pk, uuid.uuid4()])
        sync_question_images(self.owner, self.question, [attachment.pk], role=ImageRole.CORRECT_ANSWER)
        self.question.is_archived = True
        self.question.save(update_fields=['is_archived'])
        with self.assertRaises(ValidationError):
            sync_question_images(self.owner, self.question, [])
        self.question.is_archived = False
        self.question.save(update_fields=['is_archived'])
        self.course.is_archived = True
        self.course.save(update_fields=['is_archived'])
        with self.assertRaises(ValidationError):
            sync_question_images(self.owner, self.question, [])

    def test_relation_replacement_failure_rolls_back_old_links(self):
        own = upload_attachment(self.owner, image_file())
        second = upload_attachment(self.owner, image_file(color=(5, 6, 7)))
        sync_question_images(self.owner, self.question, [own.pk])
        with patch.object(QuestionImage.objects, 'bulk_create', side_effect=IntegrityError('synthetic failure')), self.assertRaises(IntegrityError):
            sync_question_images(self.owner, self.question, [second.pk])
        self.assertEqual(self.question.image_links.get().attachment_id, own.pk)

    def test_snapshots_keep_images_after_question_replaced_and_replay(self):
        first = upload_attachment(self.owner, image_file('original-name.png'))
        second = upload_attachment(self.owner, image_file('new-name.png', color=(12, 23, 34)))
        sync_question_images(self.owner, self.question, [first.pk])
        review = self.make_review()
        snapshots = snapshot_question_images(self.question, review)
        self.assertEqual(snapshots[0].name_snapshot, 'original-name.png')
        sync_question_images(self.owner, self.question, [second.pk])
        replay = snapshot_question_images(self.question, review)
        self.assertEqual([snapshot.attachment_id for snapshot in replay], [first.pk])
        self.assertEqual(review.image_snapshots.count(), 1)
        self.assertEqual(review.image_manifest.image_count, 1)
        self.assertTrue(attachment_path(first).exists())

    def test_empty_snapshot_is_frozen_too(self):
        review = self.make_review()
        self.assertEqual(snapshot_question_images(self.question, review), [])
        attachment = upload_attachment(self.owner, image_file())
        sync_question_images(self.owner, self.question, [attachment.pk])
        self.assertEqual(snapshot_question_images(self.question, review), [])
        self.assertEqual(review.image_manifest.image_count, 0)

    def test_snapshot_foreign_question_rejected(self):
        review = self.make_review(self.other_question)
        with self.assertRaises(ValidationError):
            snapshot_question_images(self.question, review)
        self.assertEqual(ReviewImageManifest.objects.count(), 0)

    def test_snapshot_failure_rolls_back_manifest(self):
        attachment = upload_attachment(self.owner, image_file())
        sync_question_images(self.owner, self.question, [attachment.pk])
        review = self.make_review()
        with patch.object(ReviewImageSnapshot.objects, 'bulk_create', side_effect=IntegrityError('synthetic failure')), self.assertRaises(IntegrityError):
            snapshot_question_images(self.question, review)
        self.assertEqual(ReviewImageManifest.objects.count(), 0)
        self.assertEqual(ReviewImageSnapshot.objects.count(), 0)

    def test_snapshot_failure_rolls_back_enclosing_review_creation(self):
        attachment = upload_attachment(self.owner, image_file())
        sync_question_images(self.owner, self.question, [attachment.pk])
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                review = self.make_review()
                with patch.object(ReviewImageSnapshot.objects, 'bulk_create', side_effect=IntegrityError('synthetic failure')):
                    snapshot_question_images(self.question, review)
        self.assertEqual(ReviewRecord.objects.count(), 0)
        self.assertEqual(ReviewImageManifest.objects.count(), 0)

    def test_snapshot_and_manifest_are_immutable(self):
        attachment = upload_attachment(self.owner, image_file())
        sync_question_images(self.owner, self.question, [attachment.pk])
        review = self.make_review()
        snapshot = snapshot_question_images(self.question, review)[0]
        for model in [snapshot, review.image_manifest]:
            with self.subTest(model=type(model).__name__), self.assertRaises(ValidationError):
                model.save()
            with self.assertRaises(ValidationError):
                model.delete()
        with self.assertRaises(ValidationError):
            ReviewImageSnapshot.objects.filter(pk=snapshot.pk).update(name_snapshot='changed')

    def test_mysql_triggers_reject_direct_update_delete_on_new_immutable_tables(self):
        if connection.vendor != 'mysql':
            self.skipTest('Raw trigger behavior requires MySQL')
        attachment = upload_attachment(self.owner, image_file())
        sync_question_images(self.owner, self.question, [attachment.pk])
        review = self.make_review()
        snapshot = snapshot_question_images(self.question, review)[0]
        cases = [
            ('attachments_attachment', 'id', attachment.pk.hex, 'display_name', 'changed'),
            ('attachments_reviewimagemanifest', 'review_id', review.pk, 'image_count', 0),
            ('attachments_reviewimagesnapshot', 'id', snapshot.pk, 'name_snapshot', 'changed'),
        ]
        for table, key, value, field, replacement in cases:
            for event in ['UPDATE', 'DELETE']:
                with self.subTest(table=table, event=event), self.assertRaises(DatabaseError):
                    with transaction.atomic(), connection.cursor() as cursor:
                        if event == 'UPDATE':
                            cursor.execute(f'UPDATE {table} SET {field}=%s WHERE {key}=%s', [replacement, value])
                        else:
                            cursor.execute(f'DELETE FROM {table} WHERE {key}=%s', [value])


class UploadHandlerTests(TestCase):
    def test_handler_caps_stream_when_header_is_absent_or_forged(self):
        request = RequestFactory().post('/attachments/upload/')
        handler = ImageUploadLimitHandler(request)
        handler.new_file('file', 'large.png', 'image/png', None)
        handler.receive_data_chunk(b'x' * MAX_INPUT_BYTES, 0)
        with self.assertRaises(StopUpload):
            handler.receive_data_chunk(b'x', MAX_INPUT_BYTES)
        self.assertIn('8 MB', request.attachment_upload_error)

    def test_handler_rejects_second_file_before_storage(self):
        request = RequestFactory().post('/attachments/upload/')
        handler = ImageUploadLimitHandler(request)
        handler.new_file('file', 'first.png', 'image/png', 10)
        with self.assertRaises(StopUpload):
            handler.new_file('file', 'second.png', 'image/png', 10)

    def test_middleware_rejects_huge_request_before_parser(self):
        request = RequestFactory().post('/attachments/upload/')
        request.META['CONTENT_LENGTH'] = str(MAX_REQUEST_BYTES + 1)
        middleware = ImageUploadLimitMiddleware(lambda request: self.fail('Body should not be parsed'))
        self.assertEqual(middleware(request).status_code, 413)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ConcurrentUploadTests(TransactionTestCase):
    # MySQL flush otherwise uses DELETE, which intentionally fails history guards.
    reset_sequences = True

    def _fixture_teardown(self):
        if connection.vendor == 'mysql':
            actual = connection.settings_dict['NAME']
            expected = settings.DATABASES['default']['TEST']['NAME']
            if actual != expected or actual not in settings.AUTHORIZED_MIGRATION_SCHEMAS or not actual.startswith('test_study_review_v2_'):
                raise RuntimeError('Refusing synthetic fixture cleanup outside the exact authorized V2 test schema.')
        if connection.vendor == 'mysql':
            # TransactionTestCase hard-codes reset_sequences=False for teardown even
            # when the class enables it for setup. Use the explicit safe flush mode.
            for alias in self._databases_names(include_mirrors=False):
                inhibit_post_migrate = self.available_apps is not None or (
                    self.serialized_rollback and hasattr(connections[alias], '_test_serialized_contents'))
                call_command('flush', verbosity=0, interactive=False, database=alias,
                    reset_sequences=True, allow_cascade=self.available_apps is not None,
                    inhibit_post_migrate=inhibit_post_migrate)
        else:
            super()._fixture_teardown()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='study-attachment-concurrent-tests-')
        self.settings_context = override_settings(PRIVATE_MEDIA_ROOT=Path(self.directory.name))
        self.settings_context.enable()
        self.addCleanup(self.settings_context.disable)
        self.addCleanup(self.directory.cleanup)
        self.owner = get_user_model().objects.create_user('concurrent_image_owner')

    def run_uploads(self, colors):
        barrier = Barrier(len(colors))
        def worker(color):
            try:
                owner = get_user_model().objects.get(pk=self.owner.pk)
                barrier.wait(timeout=12)
                return upload_attachment(owner, image_file(color=color)).pk
            except ValidationError:
                return 'quota-rejected'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(colors)) as executor:
            futures = [executor.submit(worker, color) for color in colors]
            return [future.result(timeout=20) for future in futures]

    def test_parallel_identical_uploads_publish_once(self):
        if connection.vendor != 'mysql':
            self.skipTest('Real select_for_update race acceptance requires MySQL')
        results = self.run_uploads([(12, 23, 34)] * 4)
        self.assertNotIn('quota-rejected', results)
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(Attachment.objects.count(), 1)
        self.assertEqual(len(list(Path(self.directory.name).rglob('*.png'))), 2)

    def test_parallel_quota_reservation_allows_only_one(self):
        if connection.vendor != 'mysql':
            self.skipTest('Real select_for_update race acceptance requires MySQL')
        from attachments.services import _normalise
        colors = [(12, 23, 34), (23, 34, 45)]
        totals = []
        for color in colors:
            full, thumb, _, _ = _normalise(image_file(color=color))
            totals.append(len(full) + len(thumb))
        with override_settings(ATTACHMENT_USER_QUOTA_BYTES=max(totals)):
            results = self.run_uploads(colors)
        self.assertEqual(results.count('quota-rejected'), 1)
        self.assertEqual(Attachment.objects.count(), 1)
        self.assertEqual(len(list(Path(self.directory.name).rglob('*.png'))), 2)

    def test_commit_failure_rolls_back_row_and_cleans_published_files(self):
        with patch.object(connection, 'commit', side_effect=DatabaseError('synthetic commit failure')):
            with self.assertRaises(DatabaseError):
                upload_attachment(self.owner, image_file())
        self.assertEqual(Attachment.objects.count(), 0)
        self.assertEqual(list(Path(self.directory.name).rglob('*.png')), [])

"""Account archives: genuine MySQL round trips, hostile packages and no-overwrite boundaries."""
from datetime import timedelta
import hashlib
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import zipfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from learning import archive
from learning.focus import command
from learning.models import Course, Chapter, KnowledgePoint, Task, WrongQuestion, QuestionKnowledgePoint
from learning.services import make_token, reveal_token, submit_review
from attachments.services import upload_attachment, sync_question_images
from . import test_focus_browser as harness


class ArchiveTests(TransactionTestCase):
    def _fixture_teardown(self):
        from django.conf import settings
        name = connection.settings_dict['NAME']
        assert name == settings.DATABASES['default']['TEST']['NAME'] and name in settings.AUTHORIZED_MIGRATION_SCHEMAS and name.startswith('test_study_review_v2_')
        with connection.cursor() as cursor:
            cursor.execute('SET FOREIGN_KEY_CHECKS=0')
            try: cursor.execute('TRUNCATE TABLE attachments_attachment')
            finally: cursor.execute('SET FOREIGN_KEY_CHECKS=1')
        harness.FocusBrowserTests._fixture_teardown(self)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings_override = override_settings(DATA_DIR=self.root, PRIVATE_DATA_ROOT=self.root/'private', PRIVATE_MEDIA_ROOT=self.root/'private/media', DESKTOP_NATIVE=False)
        self.settings_override.enable(); self.addCleanup(self.settings_override.disable)
        (self.root/'private').mkdir()
        self.user = get_user_model().objects.create_user('synthetic_archive_source', password='Synthetic-test-only-52')
        self.course = Course.objects.create(owner=self.user, name='合成数据库课程')
        chapter = Chapter.objects.create(course=self.course, name='关系模型')
        section = Chapter.objects.create(course=self.course, name='关系代数', parent=chapter)
        point = KnowledgePoint.objects.create(course=self.course, chapter=section, name='选择与投影')
        self.question = WrongQuestion.objects.create(course=self.course, title='合成备份题', content='合成数据', original_answer='合成原答', error_reason='概念混淆', correct_answer='关系代数', next_review_date=timezone.localdate())
        QuestionKnowledgePoint.objects.create(question=self.question, knowledge_point=point)
        self.task = Task.objects.create(course=self.course, title='合成任务', due_date=timezone.localdate())
        image = io.BytesIO(); Image.new('RGB', (20, 16), '#507070').save(image, format='PNG')
        self.attachment = upload_attachment(self.user, SimpleUploadedFile('synthetic.png', image.getvalue(), content_type='image/png'))
        sync_question_images(self.user, self.question, [str(self.attachment.pk)])
        token = reveal_token(make_token(self.user, 'review', self.question), self.user, self.question)
        submit_review(self.user, self.question.pk, {'answer': '合成作答', 'rating': 'good'}, token)
        now = timezone.now().replace(microsecond=123456)
        session = command(self.user, 'start', course_id=self.course.pk, task_id=self.task.pk, now=now-timedelta(minutes=5))
        command(self.user, 'finish', session.pk, now=now)
        from assistant.models import ChatSession, Message, MessageAttachment, Draft
        from ai_gateway.models import Account, RequestLedger, MessageContext
        import uuid
        chat = ChatSession.objects.create(owner=self.user, title='合成本地对话')
        message = Message.objects.create(session=chat, role='user', text='合成消息', status='saved')
        MessageAttachment.objects.create(message=message, attachment=self.attachment)
        Draft.objects.create(owner=self.user, session=chat, source_message=message, operation='update_task', title='合成建议', payload={'title':'合成建议'}, after_snapshot={'title':'合成建议'}, target_id=self.task.pk, request_hash='0'*64, expires_at=now+timedelta(days=1))
        account = Account.objects.create(owner=self.user)
        RequestLedger.objects.create(owner=self.user, account=account, request_id=uuid.uuid4(), request_hash='1'*64, state='failed', pricing_snapshot={'synthetic':True}, input_token_ceiling=1, output_token_ceiling=1, reserved_cny=0, held_cny=0, failure_code='synthetic_no_network')
        MessageContext.objects.create(message=message, owner=self.user)

    def package(self):
        with archive.export_account(self.user) as stream:
            return stream.read()

    def rewrite(self, payload, mutate=None, extra=None):
        with zipfile.ZipFile(io.BytesIO(payload)) as source:
            files = {name: source.read(name) for name in source.namelist()}
        manifest = json.loads(files['manifest.json'])
        rows = json.loads(files['records.json'])
        if mutate: mutate(manifest, rows)
        files['records.json'] = archive.dump_json(rows)
        manifest['files']['records.json'] = {'bytes': len(files['records.json']), 'sha256': hashlib.sha256(files['records.json']).hexdigest()}
        files['manifest.json'] = archive.dump_json(manifest)
        if extra: files.update(extra)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as result:
            for name, value in files.items(): result.writestr(name, value)
        output.seek(0); return output

    def test_round_trip_preserves_history_images_microseconds_and_credentials(self):
        now = timezone.now()
        paused = command(self.user, 'start', now=now-timedelta(seconds=60))
        command(self.user, 'pause', paused.pk, now=now)
        payload = self.package()
        checked = archive.inspect_archive(io.BytesIO(payload))
        self.assertEqual(checked.summary()['models'], 22)
        self.assertEqual(checked.summary()['images'], 1)
        self.assertTrue(all(checked.manifest['models'].values()))
        self.assertNotIn(b'password', payload)
        # Guarded test-schema cleanup is not a product restore/merge operation.
        self._fixture_teardown()
        destination = self.root/'destination'; (destination/'private').mkdir(parents=True)
        with override_settings(DATA_DIR=destination, PRIVATE_DATA_ROOT=destination/'private', PRIVATE_MEDIA_ROOT=destination/'private/media'):
            target = get_user_model().objects.create_user(pk=712, username='synthetic_existing_target', password='Synthetic-target-only-73')
            password_hash = target.password
            result = archive.restore_account(io.BytesIO(payload), target, expected_database=connection.settings_dict['NAME'], confirmed=True)
            self.assertTrue(result['restored'])
            target.refresh_from_db(); self.assertEqual(target.password, password_hash)
            self.assertEqual(Course.objects.get().owner_id, 712)
            from learning.focus import seconds
            from learning.models import FocusSession
            restored_pause = FocusSession.objects.get(pk=paused.pk)
            self.assertEqual(restored_pause.status, 'paused')
            self.assertEqual(seconds(restored_pause, now+timedelta(hours=2)), 60)
            restored = archive.export_account(target)
            after = archive.inspect_archive(restored); restored.close()
            self.assertEqual(after.manifest['models'], checked.manifest['models'])
            for row in checked.records:
                model = archive.models()[row['model']]
                for field in archive.fields(model):
                    if field.is_relation and field.related_model is get_user_model(): row['fields'][field.name] = 712
            self.assertEqual(after.records, checked.records)
            self.assertEqual({k:v for k,v in after.manifest['files'].items() if k.startswith('media/')}, {k:v for k,v in checked.manifest['files'].items() if k.startswith('media/')})
            with self.assertRaises(archive.ArchiveError):
                archive.restore_account(io.BytesIO(payload), target, expected_database=connection.settings_dict['NAME'], confirmed=True)
            self.assertEqual(Course.objects.count(), 1)

    def test_corruption_dependencies_and_versions_fail_before_writes(self):
        payload = self.package(); counts = {name: model.objects.count() for name,model in archive.models().items()}
        changes = [lambda m,r: m.update(format='studyreview-private-account-v1'), lambda m,r: m.update(schema='wrong'),
            lambda m,r: next(row for row in r if row['model']=='learning.chapter')['fields'].update(course=999999),
            lambda m,r: next(row for row in r if row['model']=='learning.course')['fields'].update(owner=999999),
            lambda m,r: next(row for row in r if row['model']=='learning.course')['fields'].update(created_at=None),
            lambda m,r: m['files']['media/'+self.attachment.storage_key+'/full.png'].update(sha256='0'*64)]
        for change in changes:
            with self.subTest(change=changes.index(change)), self.assertRaises(archive.ArchiveError):
                archive.inspect_archive(self.rewrite(payload, change))
        with self.assertRaises(archive.ArchiveError): archive.inspect_archive(self.rewrite(payload, extra={'../escape': b'x'}))
        self.assertEqual(counts, {name: model.objects.count() for name,model in archive.models().items()})

    def test_other_account_excluded_and_target_conflicts_reported(self):
        other = get_user_model().objects.create_user('synthetic_other')
        Course.objects.create(owner=other, name='Other private course')
        checked = archive.inspect_archive(io.BytesIO(self.package()))
        self.assertEqual(checked.manifest['models']['learning.course'], 1)
        self.assertFalse(archive.target_report(self.user)['ready'])

    def test_running_focus_rejected_without_mutation(self):
        session = command(self.user, 'start')
        with self.assertRaisesMessage(archive.ArchiveError, '仍在运行'): self.package()
        session.refresh_from_db(); self.assertEqual(session.status, 'running')

    def test_export_routes_require_login_post_and_csrf_and_preflight_does_not_import(self):
        self.assertEqual(self.client.get(reverse('backup')).status_code, 302)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('backup')), '不是完整备份')
        self.assertEqual(self.client.get(reverse('backup-export')).status_code, 405)
        strict = Client(enforce_csrf_checks=True); strict.force_login(self.user)
        self.assertEqual(strict.post(reverse('backup-export')).status_code, 403)
        payload = self.package()
        response = self.client.post(reverse('backup'), {'archive': SimpleUploadedFile('test.zip', payload)})
        self.assertContains(response, '预检结果 · 未执行导入')
        self.assertContains(response, '拒绝合并')
        self.assertEqual(Course.objects.count(), 1)

    def test_native_export_stays_in_current_account_directory(self):
        self.client.force_login(self.user)
        with override_settings(DESKTOP_NATIVE=True):
            response = self.client.post(reverse('backup-export'))
            self.assertContains(response, '账号学习资料包已保存')
            from html.parser import HTMLParser
            class FormTargets(HTMLParser):
                target = None
                def handle_starttag(self, tag, attrs):
                    attrs = dict(attrs)
                    if tag == 'form' and attrs.get('enctype') == 'multipart/form-data': self.target = attrs.get('action')
            form = FormTargets(); form.feed(response.content.decode())
            self.assertEqual(form.target, reverse('backup'))
        files = list((self.root/'private/exports'/str(self.user.pk)).glob('*.zip'))
        self.assertEqual(len(files), 1)
        with files[0].open('rb') as source: self.assertEqual(archive.inspect_archive(source).summary()['images'], 1)
        with override_settings(DESKTOP_NATIVE=True):
            result = self.client.post(form.target, {'archive': SimpleUploadedFile('saved.zip',files[0].read_bytes())})
        self.assertContains(result, '预检结果 · 未执行导入')
        self.assertEqual(len(list(files[0].parent.glob('*.zip'))), 1)

    def test_restore_failure_rolls_back_and_blocks_retry_and_desktop_launch(self):
        payload = self.package(); self._fixture_teardown()
        destination = self.root/'failed'; (destination/'private').mkdir(parents=True)
        with override_settings(DATA_DIR=destination, PRIVATE_DATA_ROOT=destination/'private', PRIVATE_MEDIA_ROOT=destination/'private/media', DEBUG=False):
            target = get_user_model().objects.create_user('synthetic_failure_target')
            with patch.object(Path, 'rename', side_effect=OSError('synthetic fault')):
                with self.assertRaisesMessage(archive.ArchiveError, '恢复未完成'):
                    archive.restore_account(io.BytesIO(payload), target, expected_database=connection.settings_dict['NAME'], confirmed=True)
            self.assertEqual(sum(model.objects.count() for model in archive.models().values()), 0)
            self.assertTrue((destination/'private/archive-restore.pending.json').exists())
            self.assertFalse(archive.target_report(target)['ready'])
            from desktop.main import build_wsgi
            from desktop.runtime import DesktopError
            with patch('django.core.wsgi.get_wsgi_application', return_value=object()):
                with self.assertRaisesMessage(DesktopError, '未完成的资料恢复'): build_wsgi()

    def test_ai_machine_key_is_explicit_restore_blocker(self):
        import uuid
        from ai_gateway.models import Account
        Account.objects.filter(owner=self.user).update(key_reference=uuid.uuid4(), enabled=False)
        result = archive.inspect_archive(io.BytesIO(self.package()))
        self.assertTrue(result.restore_blockers)

    def test_missing_media_duplicates_and_bad_focus_interval_are_rejected(self):
        payload = self.package()
        mutations = [lambda m,r: m['files'].pop('media/'+self.attachment.storage_key+'/thumbnail.png'),
            lambda m,r: next(row for row in r if row['model']=='learning.focusinterval')['fields'].update(ended_at='2000-01-01T00:00:00+00:00'),
            lambda m,r: next(row for row in r if row['model']=='learning.chapter' and row['fields']['parent'])['fields'].update(name='关系模型')]
        for mutation in mutations:
            with self.subTest(index=mutations.index(mutation)), self.assertRaises(archive.ArchiveError):
                archive.inspect_archive(self.rewrite(payload, mutation))
        duplicate=io.BytesIO(payload)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(duplicate,'a') as result: result.writestr('manifest.json', b'{}')
        with self.assertRaises(archive.ArchiveError): archive.inspect_archive(duplicate)

    def test_restore_requires_explicit_exact_isolated_target(self):
        payload = self.package()
        for database,confirmed in [(connection.settings_dict['NAME'],False),('unrelated_database',True)]:
            with self.assertRaises(archive.ArchiveError): archive.restore_account(io.BytesIO(payload),self.user,expected_database=database,confirmed=confirmed)
        self.assertEqual(Course.objects.count(),1)

    def test_commit_failure_retains_media_and_marker_and_rolls_back_database(self):
        from django.db import DatabaseError
        payload = self.package(); self._fixture_teardown()
        destination = self.root/'commit-failure'; (destination/'private').mkdir(parents=True)
        with override_settings(DATA_DIR=destination, PRIVATE_DATA_ROOT=destination/'private', PRIVATE_MEDIA_ROOT=destination/'private/media'):
            target = get_user_model().objects.create_user('synthetic_commit_failure')
            with patch.object(connection, 'commit', side_effect=DatabaseError('synthetic commit failure')):
                with self.assertRaises(archive.ArchiveError):
                    archive.restore_account(io.BytesIO(payload),target,expected_database=connection.settings_dict['NAME'],confirmed=True)
            self.assertEqual(sum(model.objects.count() for model in archive.models().values()),0)
            self.assertTrue((destination/'private/archive-restore.pending.json').exists())
            self.assertEqual(len(list((destination/'private/media').rglob('*.png'))),2)
            self.assertFalse(archive.target_report(target)['ready'])

    def test_post_commit_cleanup_failure_never_invites_a_duplicate_restore(self):
        payload = self.package(); counts = {name:model.objects.count() for name,model in archive.models().items()}
        self._fixture_teardown()
        destination = self.root/'cleanup-failure'; (destination/'private').mkdir(parents=True)
        with override_settings(DATA_DIR=destination, PRIVATE_DATA_ROOT=destination/'private', PRIVATE_MEDIA_ROOT=destination/'private/media'):
            target = get_user_model().objects.create_user('synthetic_cleanup_failure')
            with patch.object(Path, 'unlink', side_effect=OSError('synthetic marker cleanup failure')):
                with self.assertRaises(archive.ArchiveError):
                    archive.restore_account(io.BytesIO(payload),target,expected_database=connection.settings_dict['NAME'],confirmed=True)
            self.assertEqual(counts,{name:model.objects.count() for name,model in archive.models().items()})
            self.assertTrue((destination/'private/archive-restore.pending.json').exists())
            self.assertFalse(archive.target_report(target)['ready'])
            with self.assertRaises(archive.ArchiveError):
                archive.restore_account(io.BytesIO(payload),target,expected_database=connection.settings_dict['NAME'],confirmed=True)
            self.assertEqual(counts,{name:model.objects.count() for name,model in archive.models().items()})


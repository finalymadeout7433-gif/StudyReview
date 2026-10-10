import json
from pathlib import Path
import tempfile
import uuid
from decimal import Decimal
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, connections, close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from assistant.providers import ChatContext
from assistant.deepseek_provider import (PeakPricing, ProviderError, RequestQuote,
    ProviderRequest, prepare_request, Usage)
from ai_gateway import services, key_store
from ai_gateway.models import Account, RequestLedger

SYNTHETIC_KEY = 'sk-' + 'synthetic-test-only-not-a-real-key'


class ConfigTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('synthetic_config_owner')
        self.other = get_user_model().objects.create_user('synthetic_config_other')
        self.client.force_login(self.user)
        self.temporary = tempfile.TemporaryDirectory(prefix='study-ai-test-')
        # The temporary path is created by this test; no real credential directory.
        self.temp_path = Path(self.temporary.name).resolve()
        self.override = override_settings(PRIVATE_DATA_ROOT=self.temp_path)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.temporary.cleanup)
        self.url = reverse('ai_gateway:config')

    def data(self, **changes):
        result = {'api_key': SYNTHETIC_KEY, 'budget_cny': '5.00', 'confirm_local_storage': True,
            'confirm_budget': True, 'confirm_destination': True, 'enable': True}
        result.update(changes)
        return result

    def post(self, data):
        return self.client.post(self.url, json.dumps(data), content_type='application/json')

    def test_manual_consent_and_missing_budget_fail_before_storage(self):
        for bad in [self.data(confirm_budget=False), self.data(confirm_local_storage=1),
                self.data(confirm_destination=False), self.data(budget_cny=''),
                self.data(budget_cny='NaN'), self.data(budget_cny='1000.01'), self.data(budget_cny='0.001')]:
            with patch('ai_gateway.key_store.write_new') as write:
                response = self.post(bad)
                self.assertEqual(response.status_code, 400)
                write.assert_not_called()
                self.assertNotIn(SYNTHETIC_KEY, response.content.decode())
        self.assertEqual(Account.objects.count(), 0)

    def test_actual_windows_dpapi_synthetic_key_status_never_returns_key(self):
        response = self.post(self.data())
        self.assertEqual(response.status_code, 200)
        status = response.json()
        self.assertTrue(status['configured'])
        self.assertFalse(status['online_connection_verified'])
        self.assertNotIn(SYNTHETIC_KEY, response.content.decode())
        self.assertNotIn('key_reference', status)
        account = Account.objects.get(owner=self.user)
        stored = list(self.temp_path.rglob('key.dpapi'))
        self.assertEqual(len(stored), 1)
        self.assertNotIn(SYNTHETIC_KEY.encode(), stored[0].read_bytes())
        self.assertEqual(key_store.read_configured(account.key_reference), SYNTHETIC_KEY)
        with patch('ai_gateway.key_store.read_configured', side_effect=AssertionError('GET不能解密')):
            self.assertEqual(self.client.get(self.url).status_code, 200)
            self.assertTrue(services.gateway_provider(self.user, uuid.uuid4()).connected)

    def test_disable_keeps_budget_and_history_and_owner_isolation(self):
        self.assertEqual(self.post(self.data()).status_code, 200)
        account = Account.objects.get(owner=self.user)
        reference = account.key_reference
        disabled = self.client.delete(self.url).json()
        self.assertFalse(disabled['enabled'])
        account.refresh_from_db()
        self.assertEqual(account.key_reference, reference)
        self.assertEqual(account.budget_cny, Decimal('5'))
        self.client.force_login(self.other)
        self.assertFalse(self.client.get(self.url).json()['configured'])
        self.assertEqual(self.post({'action': 'disable'}).status_code, 200)
        account.refresh_from_db()
        self.assertFalse(account.enabled)
        self.assertEqual(Account.objects.count(), 1)

    def test_config_requires_login_and_csrf(self):
        self.assertEqual(Client().get(self.url).status_code, 401)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(protected.post(self.url, json.dumps(self.data()), content_type='application/json').status_code, 403)
        self.assertFalse(Account.objects.exists())

    def test_file_failure_and_late_db_failure_clean_only_new_ciphertext(self):
        with patch('ai_gateway.key_store.os.fsync', side_effect=OSError('synthetic failure')):
            self.assertEqual(self.post(self.data()).status_code, 400)
        self.assertFalse(Account.objects.exists())
        self.assertFalse(list(self.temp_path.rglob('*.dpapi')))
        account = Account.objects.create(owner=self.user)
        with patch('ai_gateway.services.Account.save', side_effect=RuntimeError('synthetic database failure')):
            response = self.post(self.data())
        self.assertEqual(response.status_code, 400)
        self.assertFalse(list(self.temp_path.rglob('*.dpapi')))
        account.refresh_from_db()
        self.assertFalse(account.enabled)
        self.assertIsNone(account.key_reference)
        self.assertNotIn(SYNTHETIC_KEY, response.content.decode())

    def test_budget_cannot_drop_below_spent_plus_unknown_hold(self):
        Account.objects.create(owner=self.user, budget_cny=5, spent_cny=1, reserved_cny=1)
        with patch('ai_gateway.key_store.write_new') as write:
            self.assertEqual(self.post(self.data(budget_cny='1.50')).status_code, 400)
            write.assert_not_called()

    def test_explicit_private_data_root_overrides_data_and_program_directories(self):
        explicit = self.temp_path / 'chosen-private'
        with override_settings(PRIVATE_DATA_ROOT=explicit, DATA_DIR=self.temp_path / 'user-data', BASE_DIR=self.temp_path / 'program'):
            self.assertEqual(key_store.root(create=True), explicit / 'ai-credentials')
            self.assertFalse((self.temp_path / 'user-data').exists())
            self.assertFalse((self.temp_path / 'program').exists())

    def test_separated_data_saves_dpapi_with_readonly_program_directory(self):
        program = self.temp_path / 'readonly-program'
        program.mkdir()
        resource = program / 'program-resource.txt'
        resource.write_text('synthetic unchanged resource', encoding='utf-8')
        data_dir = self.temp_path / 'mutable-user-data'
        actual_mkdir, actual_open = Path.mkdir, Path.open
        def reject_program_mkdir(path, *args, **kwargs):
            if path.resolve(strict=False).is_relative_to(program):
                raise PermissionError('Synthetic program directory is read-only')
            return actual_mkdir(path, *args, **kwargs)
        def reject_program_write(path, mode='r', *args, **kwargs):
            if path.resolve(strict=False).is_relative_to(program) and any(flag in mode for flag in 'wxa+'):
                raise PermissionError('Synthetic program resources are read-only')
            return actual_open(path, mode, *args, **kwargs)
        # Simulate a genuine write-denied program path, rather than Windows' weak
        # directory read-only attribute; pre-fix BASE_DIR fallback fails this test.
        with override_settings(PRIVATE_DATA_ROOT=None, DATA_DIR=data_dir, BASE_DIR=program), \
                patch.object(Path, 'mkdir', reject_program_mkdir), patch.object(Path, 'open', reject_program_write):
            reference = key_store.write_new(SYNTHETIC_KEY)
            expected = data_dir / 'private' / 'ai-credentials'
            self.assertEqual(key_store.root(), expected)
            self.assertEqual(key_store.read_configured(reference), SYNTHETIC_KEY)
            ciphertext = expected / reference.hex / 'key.dpapi'
            self.assertTrue(ciphertext.is_file())
            self.assertNotIn(SYNTHETIC_KEY.encode(), ciphertext.read_bytes())
            key_store.remove_new(reference)
        self.assertEqual(resource.read_text(encoding='utf-8'), 'synthetic unchanged resource')
        self.assertEqual(list(program.iterdir()), [resource])

    def test_legacy_project_without_data_dir_keeps_private_ai_compatibility(self):
        program = self.temp_path / 'legacy-project'
        with override_settings(PRIVATE_DATA_ROOT=None, DATA_DIR=None, BASE_DIR=program):
            self.assertEqual(key_store.root(create=True), program / 'private' / 'ai')


class GatewayLedgerTests(TransactionTestCase):
    def _fixture_teardown(self):
        if connection.vendor == 'mysql':
            name = connection.settings_dict['NAME']
            expected = settings.DATABASES['default']['TEST']['NAME']
            if (settings.SETTINGS_MODULE not in {'config.v2_chat_test_settings', 'config.v2_integrated_test_settings'} or name != expected
                    or not name.startswith('test_study_review_v2_')
                    or name not in settings.AUTHORIZED_MIGRATION_SCHEMAS):
                raise RuntimeError('Refusing cleanup outside exact synthetic chat test schema.')
            with connection.cursor() as cursor:
                cursor.execute('SET FOREIGN_KEY_CHECKS=0')
                try:
                    for table in ('attachments_reviewimagesnapshot', 'attachments_reviewimagemanifest',
                            'learning_reviewrecord', 'attachments_attachment'):
                        cursor.execute(f'TRUNCATE TABLE `{table}`')
                finally:
                    cursor.execute('SET FOREIGN_KEY_CHECKS=1')
        super()._fixture_teardown()

    def setUp(self):
        if connection.vendor != 'mysql':
            self.skipTest('Budget locking tests require MySQL.')
        self.user = get_user_model().objects.create_user('synthetic_budget_owner')
        self.other = get_user_model().objects.create_user('synthetic_budget_other')
        self.reference = uuid.uuid4()
        from django.utils import timezone
        self.account = Account.objects.create(owner=self.user, budget_cny=5, enabled=True,
            key_reference=self.reference, consent_at=timezone.now())
        self.pricing = PeakPricing()

    def quote(self, request_id=None, amount_tokens=1000):
        return RequestQuote(request_id or uuid.uuid4(), 'a' * 64, amount_tokens, 2048,
            self.pricing.ceiling(amount_tokens, 2048), self.pricing.version)

    def reserve(self, quote=None):
        return services.reserve(self.user, quote or self.quote(), self.pricing, key_reference=self.reference)

    def persist(self, reservation):
        return services.persist_state(self.user, reservation, key_reference=self.reference)

    def context(self):
        return ChatContext('Untrusted data only.', ({'role': 'user', 'text': '合成问题'},), (), 1, 0)

    def test_reserve_commit_dispatch_commit_settle_once_and_peak_estimate(self):
        quote = self.quote()
        reservation = self.reserve(quote)
        self.account.refresh_from_db()
        self.assertEqual(self.account.reserved_cny, quote.maximum_cost_cny)
        reservation.begin(quote)
        self.persist(reservation)
        self.assertTrue(RequestLedger.objects.get(request_id=quote.request_id).dispatched)
        reservation.settle(Usage(100, 25, 0, 100))
        self.persist(reservation)
        self.persist(reservation)
        self.account.refresh_from_db()
        self.assertEqual(self.account.spent_cny, self.pricing.estimate(reservation.usage))
        self.assertEqual(self.account.reserved_cny, 0)
        with self.assertRaises(ProviderError):
            self.reserve(quote)

    def test_timeout_keeps_hold_no_retry_or_secret_metadata(self):
        class TimeoutTransport:
            calls = 0
            def send(inner, payload, api_key, timeout):
                inner.calls += 1
                self.assertFalse(connection.in_atomic_block)
                self.assertTrue(RequestLedger.objects.get(request_id=request_id).dispatched)
                raise ProviderError('request_timeout', '合成超时', outcome_uncertain=True)
        request_id = uuid.uuid4()
        transport = TimeoutTransport()
        provider = services.GatewayProvider(self.user, request_id, transport=transport)
        with patch('ai_gateway.key_store.read_configured', return_value=SYNTHETIC_KEY):
            for _ in range(2):
                with self.assertRaises(ProviderError):
                    provider.respond(self.context())
        self.assertEqual(transport.calls, 1)
        ledger = RequestLedger.objects.get(request_id=request_id)
        self.assertEqual(ledger.state, 'uncertain')
        self.assertGreater(ledger.held_cny, 0)
        self.account.refresh_from_db()
        self.assertEqual(self.account.reserved_cny, ledger.held_cny)
        self.assertEqual(self.account.spent_cny, 0)
        self.assertNotIn(SYNTHETIC_KEY, repr(ledger.__dict__))
        self.assertNotIn('合成问题', repr(ledger.__dict__))

    def test_configuration_disabled_before_dispatch_stops_and_releases(self):
        quote = self.quote()
        reservation = self.reserve(quote)
        services.disable(self.user)
        reservation.begin(quote)
        with self.assertRaises(ProviderError):
            self.persist(reservation)
        reservation.fail('configuration_changed', uncertain=False)
        self.persist(reservation)
        self.account.refresh_from_db()
        self.assertEqual(self.account.reserved_cny, 0)
        ledger = RequestLedger.objects.get(request_id=quote.request_id)
        self.assertFalse(ledger.dispatched)
        self.assertEqual(ledger.state, 'failed')

    def test_mock_success_sends_outside_locks_and_no_key_in_payload(self):
        class SyntheticTransport:
            calls = 0
            def send(inner, payload, api_key, timeout):
                inner.calls += 1
                self.assertFalse(connection.in_atomic_block)
                self.assertNotIn(SYNTHETIC_KEY.encode(), payload)
                self.assertTrue(RequestLedger.objects.get(request_id=request_id).dispatched)
                return json.dumps({'usage': {'prompt_tokens': 100, 'completion_tokens': 25},
                    'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
                        'content': json.dumps({'text': '合成回答，仅测试', 'drafts': []})}}]}).encode()
        request_id = uuid.uuid4()
        transport = SyntheticTransport()
        with patch('ai_gateway.key_store.read_configured', return_value=SYNTHETIC_KEY):
            response = services.GatewayProvider(self.user, request_id, transport=transport).respond(self.context())
        self.assertEqual(response.text, '合成回答，仅测试')
        self.assertEqual(transport.calls, 1)
        self.assertEqual(RequestLedger.objects.get(request_id=request_id).state, 'succeeded')

    def test_missing_config_or_other_owner_never_decrypts(self):
        with patch('ai_gateway.key_store.read_configured', side_effect=AssertionError('不能读别人的key')):
            self.assertFalse(services.gateway_provider(self.other, uuid.uuid4()).connected)
            with self.assertRaises(ProviderError):
                services.GatewayProvider(self.other, uuid.uuid4(), transport=object()).respond(self.context())

    def test_request_uuid_never_returns_reusable_reservation(self):
        quote = self.quote()
        self.reserve(quote)
        with self.assertRaises(ProviderError):
            self.reserve(quote)
        self.assertEqual(RequestLedger.objects.count(), 1)

    def test_final_settlement_storage_failure_keeps_committed_hold(self):
        class SyntheticTransport:
            def send(inner, payload, api_key, timeout):
                return json.dumps({'usage': {'prompt_tokens': 100, 'completion_tokens': 25},
                    'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
                        'content': json.dumps({'text': '合成结果', 'drafts': []})}}]}).encode()
        original = services.persist_state
        def fail_settlement(user, reservation, **kwargs):
            if reservation.state != 'reserved':
                raise RuntimeError('synthetic settlement storage failure')
            return original(user, reservation, **kwargs)
        request_id = uuid.uuid4()
        with patch('ai_gateway.key_store.read_configured', return_value=SYNTHETIC_KEY), patch('ai_gateway.services.persist_state', side_effect=fail_settlement):
            with self.assertRaises(ProviderError) as error:
                services.GatewayProvider(self.user, request_id, transport=SyntheticTransport()).respond(self.context())
        self.assertTrue(error.exception.outcome_uncertain)
        ledger = RequestLedger.objects.get(request_id=request_id)
        self.assertTrue(ledger.dispatched)
        self.assertEqual(ledger.state, 'reserved')
        self.account.refresh_from_db()
        self.assertEqual(self.account.reserved_cny, ledger.held_cny)
        self.assertGreater(ledger.held_cny, 0)

    def test_parallel_same_uuid_reservation_is_exactly_one(self):
        quote = self.quote()
        barrier = Barrier(4)
        def worker(_):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.user.pk)
                barrier.wait(timeout=10)
                try:
                    services.reserve(user, quote, self.pricing, key_reference=self.reference)
                    return 'reserved'
                except ProviderError:
                    return 'blocked'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(worker, range(4)))
        self.assertEqual(results.count('reserved'), 1)
        self.assertEqual(results.count('blocked'), 3)
        self.assertEqual(RequestLedger.objects.count(), 1)

    def test_transport_error_with_secret_in_exception_never_logs_or_exposes_it(self):
        class UnsafeTransport:
            def send(inner, payload, api_key, timeout):
                raise RuntimeError('synthetic exception contains ' + SYNTHETIC_KEY)
        with patch('ai_gateway.key_store.read_configured', return_value=SYNTHETIC_KEY), patch('logging.Logger._log') as log:
            with self.assertRaises(ProviderError) as caught:
                services.GatewayProvider(self.user, uuid.uuid4(), transport=UnsafeTransport()).respond(self.context())
        self.assertNotIn(SYNTHETIC_KEY, str(caught.exception))
        self.assertNotIn(SYNTHETIC_KEY, repr(log.call_args_list))
        self.assertNotIn(SYNTHETIC_KEY, repr(list(RequestLedger.objects.values())))

    def test_usage_above_reservation_remains_held_and_no_retry(self):
        quote = self.quote(amount_tokens=1000)
        reservation = self.reserve(quote)
        reservation.begin(quote)
        self.persist(reservation)
        with self.assertRaises(ProviderError):
            reservation.settle(Usage(2000, 100, 0, 2000))
        self.persist(reservation)
        ledger = RequestLedger.objects.get(request_id=quote.request_id)
        self.assertEqual(ledger.state, 'uncertain')
        self.assertGreaterEqual(ledger.held_cny, quote.maximum_cost_cny)
        self.assertEqual(ledger.failure_code, 'usage_exceeded_bound')
        self.account.refresh_from_db()
        self.assertFalse(self.account.enabled)
        status = services.configuration_status(self.user)
        self.assertFalse(status['connected'])
        self.assertEqual(status['state'], 'billing_review_required')
        with self.assertRaises(ProviderError):
            self.reserve(self.quote())
        self.assertEqual(RequestLedger.objects.count(), 1)
        with patch('ai_gateway.key_store.read_configured', side_effect=AssertionError('blocked account must not decrypt')):
            with self.assertRaises(ProviderError):
                services.GatewayProvider(self.user, uuid.uuid4(), transport=object()).respond(self.context())
        self.assertEqual(self.account.reserved_cny, ledger.held_cny)

    def test_bound_violation_blocks_previously_reserved_request_before_dispatch_and_reenable(self):
        first = self.reserve(self.quote())
        second_quote = self.quote()
        second = self.reserve(second_quote)
        first.begin(self.quote(request_id=first.request_id))
        self.persist(first)
        with self.assertRaises(ProviderError):
            first.settle(Usage(2000, 100, 0, 2000))
        self.persist(first)
        second.begin(second_quote)
        with self.assertRaises(ProviderError):
            self.persist(second)
        self.assertFalse(RequestLedger.objects.get(request_id=second.request_id).dispatched)
        with patch('ai_gateway.key_store.write_new', side_effect=AssertionError('must not create a new key')):
            with self.assertRaises(ValidationError):
                services.configure(self.user, {'api_key': SYNTHETIC_KEY, 'budget_cny': '5.00',
                    'confirm_local_storage': True, 'confirm_budget': True, 'confirm_destination': True, 'enable': True})
        self.account.refresh_from_db()
        self.assertFalse(self.account.enabled)
        self.assertGreater(self.account.reserved_cny, 0)

    def test_legacy_bound_ledger_blocks_even_if_account_was_enabled(self):
        quote = self.quote()
        reservation = self.reserve(quote)
        reservation.begin(quote)
        self.persist(reservation)
        with self.assertRaises(ProviderError):
            reservation.settle(Usage(2000, 100, 0, 2000))
        self.persist(reservation)
        Account.objects.filter(pk=self.account.pk).update(enabled=True)
        with self.assertRaises(ProviderError):
            self.reserve(self.quote())
        self.assertFalse(services.configuration_status(self.user)['connected'])

    def test_budget_concurrent_reservations_cannot_exceed_limit(self):
        quote = self.quote()
        Account.objects.filter(pk=self.account.pk).update(budget_cny=quote.maximum_cost_cny)
        barrier = Barrier(2)
        def worker(_):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.user.pk)
                barrier.wait(timeout=10)
                try:
                    services.reserve(user, self.quote(), self.pricing, key_reference=self.reference)
                    return 'reserved'
                except ProviderError:
                    return 'blocked'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(worker, range(2))), ['blocked', 'reserved'])
        self.account.refresh_from_db()
        self.assertEqual(self.account.reserved_cny, self.account.budget_cny)
        self.assertEqual(RequestLedger.objects.count(), 1)
